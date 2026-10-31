"""Habilidades extras do Atlas: lembretes/alarmes, controle do PC e enxergar a tela."""
import ctypes
import datetime
import io
import json
import re
import subprocess
import threading
from pathlib import Path

import ollama

from ferramentas import ARQUIVOS, BASE, CONFIG

# ---------- lembretes e alarmes ----------
ARQ_LEMBRETES = BASE / "lembretes.json"
_trava = threading.Lock()


def _carregar() -> list[dict]:
    return json.loads(ARQ_LEMBRETES.read_text(encoding="utf-8")) if ARQ_LEMBRETES.exists() else []


def _salvar(lista: list[dict]):
    ARQ_LEMBRETES.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")


def criar_lembrete(mensagem: str, minutos_a_partir_de_agora: int = 0, horario: str = "", data: str = "") -> str:
    """Cria um lembrete ou alarme que o Atlas fala em voz alta na hora certa.
    Use minutos_a_partir_de_agora para 'daqui a X minutos/horas' (horas * 60), ou horario 'HH:MM' (e opcionalmente
    data 'DD/MM') para uma hora certa. Ex: 'me lembra as 15h de ligar pro fornecedor' -> horario='15:00'."""
    agora = datetime.datetime.now()
    if minutos_a_partir_de_agora:
        quando = agora + datetime.timedelta(minutes=int(minutos_a_partir_de_agora))
    elif horario:
        m = re.match(r"(\d{1,2})(?:[:h](\d{2}))?", horario.strip())
        if not m:
            return "Nao entendi o horario."
        quando = agora.replace(hour=int(m[1]), minute=int(m[2] or 0), second=0, microsecond=0)
        if data:
            d = re.match(r"(\d{1,2})/(\d{1,2})", data)
            if d:
                quando = quando.replace(day=int(d[1]), month=int(d[2]))
        elif quando <= agora:
            quando += datetime.timedelta(days=1)
    else:
        return "Preciso saber quando: daqui a quantos minutos ou em que horario."
    with _trava:
        lista = _carregar()
        lista.append({"mensagem": mensagem, "quando": quando.isoformat(timespec="minutes"), "avisado": False})
        _salvar(lista)
    return f"Lembrete criado para {quando:%d/%m as %H:%M}: {mensagem}."


def listar_lembretes() -> str:
    """Lista os lembretes e alarmes pendentes."""
    pend = [l for l in _carregar() if not l["avisado"]]
    if not pend:
        return "Nenhum lembrete pendente."
    return "; ".join(f"{datetime.datetime.fromisoformat(l['quando']):%d/%m %H:%M} - {l['mensagem']}" for l in pend)


def cancelar_lembrete(texto: str) -> str:
    """Cancela lembretes pendentes que contenham o texto informado (ou 'todos')."""
    with _trava:
        lista = _carregar()
        alvo = [l for l in lista if not l["avisado"] and (texto.lower() == "todos" or texto.lower() in l["mensagem"].lower())]
        for l in alvo:
            l["avisado"] = True
        _salvar(lista)
    return f"Cancelei {len(alvo)} lembrete(s)."


def lembretes_vencidos() -> list[str]:
    """Usado pela interface: devolve (uma unica vez) os lembretes cuja hora chegou."""
    agora = datetime.datetime.now()
    with _trava:
        lista = _carregar()
        vencidos = [l for l in lista if not l["avisado"] and datetime.datetime.fromisoformat(l["quando"]) <= agora]
        for l in vencidos:
            l["avisado"] = True
        if vencidos:
            _salvar(lista)
    return [l["mensagem"] for l in vencidos]


# ---------- controle do PC ----------
_TECLAS = {"aumentar_volume": 0xAF, "diminuir_volume": 0xAE, "mudo": 0xAD,
           "proxima_musica": 0xB0, "musica_anterior": 0xB1, "tocar_pausar": 0xB3}


def _tecla(vk: int, vezes: int = 1):
    for _ in range(vezes):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


# Ultima fala do usuario (o servidor preenche). Acoes drasticas so rodam se o pedido estiver EXPLICITO nela,
# porque o modelo local as vezes "adivinha" (ex.: ouviu "para" e bloqueou a tela).
ultima_fala = ""
EXIGE_PALAVRAS = {"bloquear_tela": (r"bloque", r"tela|computador|pc"),
                  "reiniciar_pc": (r"rein[ií]ci|restart", r"computador|\bpc\b|m[aá]quina|windows|sistema"),
                  "desligar_pc": (r"deslig|shutdown", r"computador|\bpc\b|m[aá]quina|windows|sistema"),
                  "suspender_pc": (r"suspend|dormir|repouso|sleep", r"computador|\bpc\b|m[aá]quina|windows|sistema"),
                  "hibernar_pc": (r"hibern",),
                  "cancelar_reinicio": (r"cancel|n[aã]o (rein[ií]ci|deslig)|desist",),   # cancelar e sempre seguro
                  "fechar_programa": (r"fech|encerr|mata|finaliz",)}
_SEM_JANELA = 0x08000000  # CREATE_NO_WINDOW


def _pedido_explicito(acao: str) -> bool:
    return all(re.search(p, ultima_fala, re.I) for p in EXIGE_PALAVRAS.get(acao, ()))


def controlar_pc(acao: str, valor: int = 0, nome: str = "") -> str:
    """Controla o PC. acao: 'aumentar_volume', 'diminuir_volume', 'definir_volume' (valor 0-100), 'mudo',
    'tocar_pausar' (musica/video), 'proxima_musica', 'musica_anterior', 'bloquear_tela',
    'reiniciar_pc' (reinicia em 60 s e roda o teste de estabilidade quando o Atlas voltar), 'desligar_pc' (em 60 s),
    'suspender_pc', 'hibernar_pc', 'cancelar_reinicio' (cancela reinicio OU desligamento agendado),
    'fechar_programa' (nome do programa em `nome`, ex: 'chrome', 'spotify').
    Acoes de energia e fechar programa SO quando o usuario pedir isso claramente."""
    acao = acao.lower().strip()
    if not _pedido_explicito(acao):
        return f"Nao executei '{acao}': o usuario nao pediu isso explicitamente. Pergunte o que ele quer."
    if acao == "bloquear_tela":
        ctypes.windll.user32.LockWorkStation()
        return "Tela bloqueada."
    if acao == "reiniciar_pc":
        ARQ_POS_REINICIO.write_text(json.dumps({"pedido_em": datetime.datetime.now().isoformat(timespec="seconds")}),
                                    encoding="utf-8")
        subprocess.run(["shutdown", "/r", "/t", "60", "/c", "Atlas: reiniciando em 60 segundos. "
                        "Diga 'cancela o reinicio' para desistir."], creationflags=subprocess.CREATE_NO_WINDOW)
        return "O computador reinicia em 60 segundos; salve o que estiver aberto. Depois rodo o teste de estabilidade."
    if acao == "desligar_pc":
        subprocess.run(["shutdown", "/s", "/t", "60", "/c", "Atlas: desligando em 60 segundos. "
                        "Diga 'Atlas, cancela o desligamento' para desistir."], creationflags=_SEM_JANELA)
        return "O computador desliga em 60 segundos; salve o que estiver aberto. Diga 'cancela' para desistir."
    if acao == "suspender_pc":
        threading.Timer(8, lambda: subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=_SEM_JANELA)).start()
        return "Vou suspender o computador em alguns segundos."
    if acao == "hibernar_pc":
        threading.Timer(8, lambda: subprocess.run(["shutdown", "/h"], creationflags=_SEM_JANELA)).start()
        return "Vou hibernar o computador em alguns segundos."
    if acao == "fechar_programa":
        alvo = re.sub(r"\.exe$", "", (nome or "").strip().lower())
        protegidos = {"", "python", "pythonw", "msedge", "ollama", "ollama app", "whisper-server", "explorer",
                      "winlogon", "csrss", "svchost", "system", "lsass"}
        if alvo in protegidos:
            return f"Nao posso fechar '{nome}': e parte do Atlas ou do Windows."
        import psutil
        apelidos = {"bloco de notas": "notepad", "navegador": "chrome", "google chrome": "chrome", "explorador": "explorer",
                    "calculadora": "calculatorapp", "whatsapp": "whatsapp", "word": "winword", "excel": "excel",
                    "antigravity": "antigravity", "vs code": "code", "visual studio code": "code", "spotify": "spotify",
                    "discord": "discord", "steam": "steam", "epic": "epicgameslauncher"}
        procura = apelidos.get(alvo, alvo).replace(" ", "")
        if procura in protegidos:
            return f"Nao posso fechar '{nome}': e parte do Atlas ou do Windows."
        fechados = 0
        for p in psutil.process_iter(["name"]):
            n = (p.info["name"] or "").lower().removesuffix(".exe")
            if procura in n.replace(" ", "") and n not in protegidos:
                try:
                    p.terminate(); fechados += 1
                except psutil.Error:
                    pass
        return f"Fechei {nome}." if fechados else f"Nao encontrei '{nome}' aberto."
    if acao == "cancelar_reinicio":
        ARQ_POS_REINICIO.unlink(missing_ok=True)
        r = subprocess.run(["shutdown", "/a"], creationflags=_SEM_JANELA)
        return "Cancelado, nao vou desligar nem reiniciar." if r.returncode == 0 else "Nao havia nada agendado."
    if acao == "definir_volume":
        _tecla(_TECLAS["diminuir_volume"], 50)                       # zera (cada toque = 2%)
        _tecla(_TECLAS["aumentar_volume"], max(0, min(100, int(valor))) // 2)
        return f"Volume em {valor}%."
    if acao in _TECLAS:
        _tecla(_TECLAS[acao], 5 if "volume" in acao else 1)          # volume: passos de 10%
        return f"Feito: {acao.replace('_', ' ')}."
    return "Acao desconhecida."


# ---------- enxergar a tela ----------
def olhar_a_tela(pergunta: str = "Descreva o que aparece na tela.") -> str:
    """Tira um print da tela do computador e analisa (ex: 'o que e esse erro na minha tela?', 'le o que esta escrito')."""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    r = ollama.chat(model=CONFIG["modelo_visao"], keep_alive=0, messages=[{
        "role": "user", "images": [buf.getvalue()],
        "content": f"Esta e a tela do computador do usuario. Responda em portugues, em ate 3 frases. {pergunta}"}])
    return r.message.content


# ---------- teste de estabilidade (tambem roda sozinho depois de um reinicio pedido ao Atlas) ----------
ARQ_POS_REINICIO = BASE / "teste-pos-reinicio.json"


def _powershell(comando: str, timeout: int = 60) -> str:
    try:
        comando = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + comando
        return subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    except Exception as e:
        return f"falhou ({e})"


def _responde(url: str) -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=5)
        return True
    except Exception as e:
        return getattr(e, "code", 0) > 0   # respondeu com erro HTTP = servico esta no ar


def teste_de_estabilidade() -> str:
    """Testa a estabilidade do PC: erros criticos e desligamentos inesperados desde o ultimo boot, erros de
    hardware (WHEA), CPU/RAM/discos sob uso, temperatura e se Ollama e o Whisper estao no ar. Salva um relatorio."""
    import psutil
    boot = datetime.datetime.fromtimestamp(psutil.boot_time())
    desde = (boot - datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
    eventos = _powershell(
        f"$d=[datetime]'{desde}'; "
        "$c=@(Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2;StartTime=$d} -EA SilentlyContinue); "
        "$k=@(Get-WinEvent -FilterHashtable @{LogName='System';Id=41,6008;StartTime=(Get-Date).AddDays(-7)} -EA SilentlyContinue); "
        "$w=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger';StartTime=(Get-Date).AddDays(-7)} -EA SilentlyContinue); "
        "$a=@(Get-WinEvent -FilterHashtable @{LogName='Application';Id=1000,1002;StartTime=$d} -EA SilentlyContinue); "
        "\"$($c.Count)|$($k.Count)|$($w.Count)|$($a.Count)\"; "
        "$c | Select -First 8 | % { \"  [$($_.TimeCreated.ToString('HH:mm'))] $($_.ProviderName): \" + "
        "($_.Message -split \"`n\")[0].Trim() }")
    linhas = eventos.splitlines() or ["?|?|?|?"]
    criticos, inesperados, whea, travamentos = (linhas[0].split("|") + ["?"] * 4)[:4]

    amostras = [psutil.cpu_percent(interval=1) for _ in range(10)]
    ram = psutil.virtual_memory()
    discos = []
    for p in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(p.mountpoint)
            discos.append(f"{p.mountpoint} {u.free / 2**30:.0f} GB livres ({u.percent:.0f}% usado)")
        except OSError:
            pass
    saude = _powershell("Get-PhysicalDisk | % { \"$($_.FriendlyName): $($_.HealthStatus)\" }", 30)
    temp = _powershell("Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -EA SilentlyContinue | "
                       "% { [math]::Round($_.CurrentTemperature/10 - 273.15) }", 20).splitlines()
    ollama_ok = _responde("http://127.0.0.1:11434/api/tags")
    whisper_ok = _responde("http://127.0.0.1:7778/")

    problemas = []
    if inesperados not in ("0", "?"):
        problemas.append(f"{inesperados} desligamento(s) inesperado(s) na ultima semana")
    if whea not in ("0", "?"):
        problemas.append(f"{whea} erro(s) de hardware WHEA na ultima semana")
    if criticos not in ("0", "?"):
        problemas.append(f"{criticos} erro(s) no log do sistema desde o boot")
    if travamentos not in ("0", "?"):
        problemas.append(f"{travamentos} programa(s) travaram desde o boot")
    if ram.percent > 90:
        problemas.append("RAM acima de 90%")
    if "Unhealthy" in saude or "Warning" in saude:
        problemas.append("um disco reporta problema de saude")
    if not ollama_ok:
        problemas.append("Ollama fora do ar")
    if not whisper_ok:
        problemas.append("Whisper na placa de video fora do ar")

    agora = datetime.datetime.now()
    relatorio = "\n".join([
        f"Teste de estabilidade do Atlas - {agora:%d/%m/%Y %H:%M}",
        f"Ultimo boot: {boot:%d/%m/%Y %H:%M} (ligado ha {int((agora - boot).total_seconds() // 60)} min)",
        "",
        f"Erros/criticos no log do sistema desde o boot: {criticos}",
        *linhas[1:],
        f"Desligamentos inesperados (Kernel-Power 41 / 6008) em 7 dias: {inesperados}",
        f"Erros de hardware WHEA em 7 dias: {whea}",
        f"Programas que travaram desde o boot: {travamentos}",
        "",
        f"CPU (10 amostras): media {sum(amostras) / len(amostras):.0f}%, pico {max(amostras):.0f}%",
        f"RAM: {ram.used / 2**30:.1f} de {ram.total / 2**30:.0f} GB ({ram.percent:.0f}%)",
        "Discos: " + "; ".join(discos),
        "Saude dos discos: " + (saude.replace("\n", "; ") or "indisponivel"),
        "Temperatura (sensor ACPI): " + (", ".join(t + " C" for t in temp if t.strip()) or "indisponivel"),
        f"Ollama: {'ok' if ollama_ok else 'FORA DO AR'} | Whisper GPU: {'ok' if whisper_ok else 'FORA DO AR'}",
        "",
        "Resultado: " + ("ESTAVEL" if not problemas else "ATENCAO - " + "; ".join(problemas)),
    ])
    caminho = ARQUIVOS / f"teste-estabilidade-{agora:%Y%m%d-%H%M}.txt"
    caminho.write_text(relatorio, encoding="utf-8")
    resumo = "Sistema estavel, nenhum problema encontrado" if not problemas else "Atencao: " + ", ".join(problemas)
    return f"{resumo}. Relatorio salvo em {caminho.name}."


def checar_pos_reinicio():
    """Chamado na partida do servidor: se o reinicio foi pedido ao Atlas, espera o sistema assentar,
    roda o teste e deixa o resultado como lembrete para ser falado."""
    if not ARQ_POS_REINICIO.exists():
        return

    def _rodar():
        import time
        time.sleep(120)   # deixa Ollama, Whisper e o resto do Windows terminarem de subir
        try:
            resultado = teste_de_estabilidade()
        except Exception as e:
            resultado = f"o teste falhou: {e}"
        ARQ_POS_REINICIO.unlink(missing_ok=True)
        with _trava:
            lista = _carregar()
            lista.append({"mensagem": f"Teste pos reinicio concluido. {resultado}",
                          "quando": datetime.datetime.now().isoformat(timespec="minutes"), "avisado": False})
            _salvar(lista)
    threading.Thread(target=_rodar, daemon=True).start()


TODAS = [criar_lembrete, listar_lembretes, cancelar_lembrete, controlar_pc, olhar_a_tela, teste_de_estabilidade]
