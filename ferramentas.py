"""Acoes que o Atlas pode executar no PC. So o que esta aqui e permitido."""
import datetime
import json
import os
import shutil
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path

BASE = Path(__file__).parent
RAIZ = BASE.parent   # pasta que contem o atlas, os projetos e os arquivos
_cfg = BASE / "config.json"
if not _cfg.exists():
    shutil.copy(BASE / "config.exemplo.json", _cfg)
CONFIG = json.loads(_cfg.read_text(encoding="utf-8-sig"))
ARQUIVOS = Path(CONFIG["pasta_arquivos"])
ARQUIVOS.mkdir(parents=True, exist_ok=True)
MEMORIA = BASE / "memoria.json"


def _antigravity_exe():
    for p in (
        Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Antigravity" / "Antigravity.exe",
        Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Antigravity IDE" / "Antigravity IDE.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Antigravity" / "Antigravity.exe",
    ):
        if p.exists():
            return str(p)
    return shutil.which("antigravity")


def abrir_programa(nome: str) -> str:
    """Abre um programa do PC pelo nome (ex: chrome, antigravity, spotify, calculadora)."""
    chave = nome.lower().strip()
    alvo = CONFIG["programas"].get(chave, chave)
    if alvo == "antigravity":
        return abrir_no_antigravity(str(RAIZ))
    try:
        os.startfile(alvo)
        return f"Abri {nome}."
    except OSError:
        return f"Nao encontrei o programa {nome}."


def abrir_site(endereco: str) -> str:
    """Abre um site no navegador."""
    if not endereco.startswith("http"):
        endereco = "https://" + endereco
    webbrowser.open(endereco)
    return f"Abri {endereco}."


def pesquisar_na_web(pergunta: str) -> str:
    """Abre uma pesquisa no Google no navegador."""
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(pergunta))
    return f"Pesquisei por {pergunta} no navegador."


def tocar_no_youtube(busca: str) -> str:
    """Abre uma busca de video ou musica no YouTube."""
    webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(busca))
    return f"Abri o YouTube com {busca}."


def criar_arquivo(nome: str, conteudo: str) -> str:
    """Cria um arquivo de texto (ex: post, roteiro, lista) na pasta de arquivos do Atlas."""
    nome = Path(nome).name or "nota.txt"
    if "." not in nome:
        nome += ".txt"
    caminho = ARQUIVOS / nome
    caminho.write_text(conteudo, encoding="utf-8")
    return f"Salvei o arquivo {caminho}."


def listar_arquivos() -> str:
    """Lista os arquivos que o Atlas ja criou."""
    itens = sorted(p.name for p in ARQUIVOS.iterdir())
    return "Arquivos: " + (", ".join(itens) if itens else "nenhum ainda.")


def ler_arquivo(nome: str) -> str:
    """Le o conteudo de um arquivo da pasta de arquivos do Atlas."""
    caminho = ARQUIVOS / Path(nome).name
    if not caminho.exists():
        return "Arquivo nao encontrado."
    return caminho.read_text(encoding="utf-8")[:4000]


def abrir_pasta_de_arquivos() -> str:
    """Abre no Explorador a pasta onde o Atlas salva os arquivos."""
    os.startfile(ARQUIVOS)
    return "Abri a pasta de arquivos."


def _achar_pasta(nome: str) -> Path | None:
    """Aceita caminho completo ou so o nome de um projeto (procura em projetos/)."""
    p = Path(nome)
    if p.is_absolute() and p.is_dir():
        return p
    projetos = Path(CONFIG.get("pasta_projetos", RAIZ / "projetos"))
    chave = "".join(c if c.isalnum() else "-" for c in nome.lower()).strip("-")
    candidatos = [d for d in projetos.glob("*") if d.is_dir() and not d.name.startswith("_")
                  and (d.name == chave or chave in d.name or d.name in chave)]
    # prefere o projeto que funciona (tem iniciar.bat), depois o com mais arquivos
    candidatos.sort(key=lambda d: (not any(d.glob("iniciar*.bat")), -sum(1 for _ in d.iterdir())))
    return candidatos[0] if candidatos else None


def executar_projeto(nome_do_projeto: str) -> str:
    """RODA (abre para usar) um programa/plataforma que o Claude ja criou, pelo nome. Use quando o usuario pedir
    para abrir, rodar, executar, iniciar ou usar um projeto. (Para ver/editar o CODIGO, use abrir_no_antigravity.)"""
    pasta = _achar_pasta(nome_do_projeto)
    if not pasta:
        nomes = ", ".join(d.name for d in PROJETOS.glob("*") if d.is_dir() and not d.name.startswith("_")) or "nenhum"
        return f"Nao achei o projeto '{nome_do_projeto}'. Projetos existentes: {nomes}."
    iniciadores = sorted(pasta.glob("iniciar*.bat")) + sorted(pasta.glob("*.bat"))
    if iniciadores:
        os.startfile(iniciadores[0])
        return f"Iniciei {pasta.name} ({iniciadores[0].name}). Ele abre em alguns segundos."
    for alvo in ("index.html", "painel.html"):
        if (pasta / alvo).exists():
            os.startfile(pasta / alvo)
            return f"Abri {alvo} de {pasta.name}."
    return f"O projeto {pasta.name} nao tem iniciar.bat. Peca ao Claude para criar um."


def listar_projetos() -> str:
    """Lista os projetos/programas que o Claude ja criou."""
    nomes = [d.name for d in PROJETOS.glob("*") if d.is_dir() and not d.name.startswith("_")]
    return "Projetos: " + (", ".join(nomes) if nomes else "nenhum ainda.")


def abrir_no_antigravity(pasta: str = str(RAIZ)) -> str:
    """Abre uma pasta ou um projeto (pelo nome) no editor Antigravity."""
    exe = _antigravity_exe()
    if not exe:
        return "Nao encontrei o Antigravity instalado."
    alvo = _achar_pasta(pasta)
    if not alvo:
        return f"Nao existe pasta ou projeto chamado '{pasta}'."
    subprocess.Popen([exe, str(alvo)])
    return f"Abri a pasta {alvo} no Antigravity."


def data_e_hora() -> str:
    """Informa a data e a hora atuais."""
    agora = datetime.datetime.now()
    return agora.strftime("Hoje e %d/%m/%Y, %H:%M.")


def lembrar(fato: str) -> str:
    """Guarda uma informacao importante sobre o usuario para lembrar no futuro."""
    dados = carregar_memoria()
    dados.append(fato)
    MEMORIA.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return "Anotado, vou lembrar disso."


def carregar_memoria() -> list:
    if MEMORIA.exists():
        return json.loads(MEMORIA.read_text(encoding="utf-8"))
    return []


def ler_noticias(assunto: str = "") -> str:
    """Busca as noticias mais recentes do Brasil (Google Noticias). Opcional: um assunto, ex: 'brinquedos', 'futebol', 'tecnologia'."""
    import urllib.request
    import xml.etree.ElementTree as ET
    base = "https://news.google.com/rss"
    url = (f"{base}/search?q={urllib.parse.quote(assunto)}&" if assunto else f"{base}?") + "hl=pt-BR&gl=BR&ceid=BR:pt-419"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    itens = ET.fromstring(urllib.request.urlopen(req, timeout=15).read()).findall(".//item")[:6]
    if not itens:
        return "Nao encontrei noticias agora."
    return "Manchetes: " + " | ".join(i.findtext("title", "").rsplit(" - ", 1)[0] for i in itens)


def status_do_pc() -> str:
    """Mostra como o computador esta agora: uso de CPU, memoria RAM, placa de video, discos e os programas mais pesados."""
    import psutil
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    partes = [f"CPU em {cpu:.0f}%", f"RAM {ram.used / 2**30:.1f} de {ram.total / 2**30:.0f} GB ({ram.percent:.0f}%)"]
    for d in ("C:\\", "D:\\", "E:\\"):
        try:
            u = psutil.disk_usage(d)
            partes.append(f"disco {d[0]} com {u.free / 2**30:.0f} GB livres")
        except OSError:
            pass
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
            "(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage').CounterSamples | Measure-Object CookedValue -Sum | % Sum"],
            capture_output=True, text=True, timeout=10).stdout.strip().replace(",", ".")
        partes.append(f"placa de video em {float(out):.0f}%")
    except Exception:
        pass
    procs = sorted(psutil.process_iter(["name", "memory_info"]), key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)
    pesados = ", ".join(f"{p.info['name']} ({p.info['memory_info'].rss / 2**20:.0f} MB)" for p in procs[:3])
    return "; ".join(partes) + f". Mais pesados: {pesados}."


def ajustar_voz(nivel_robotico: float) -> str:
    """Ajusta o quanto a voz do assistente soa robotica: 0 = natural, 0.25 = sutil, 0.5 = medio, 1 = bem robotica."""
    nivel = max(0.0, min(1.0, float(nivel_robotico)))
    CONFIG["robotico"] = nivel
    (BASE / "config.json").write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Voz ajustada para nivel robotico {nivel:.2f}."


# ---------- Claude como engenheiro: constroi ferramentas e programas de verdade ----------
PROJETOS = Path(CONFIG.get("pasta_projetos", RAIZ / "projetos"))
ARQ_TAREFAS = BASE / "tarefas.json"
TAREFAS: dict[str, dict] = json.loads(ARQ_TAREFAS.read_text(encoding="utf-8")) if ARQ_TAREFAS.exists() else {}
for _t in TAREFAS.values():   # servidor reiniciou no meio: o processo do Claude se perdeu
    if _t["status"] == "em andamento":
        _t["status"] = "interrompido"


def _salvar_tarefas():
    ARQ_TAREFAS.write_text(json.dumps(TAREFAS, ensure_ascii=False, indent=1), encoding="utf-8")


def arquivos_do_projeto(pasta: str) -> list[str]:
    raiz = Path(pasta)
    return sorted(str(p.relative_to(raiz)) for p in raiz.rglob("*") if p.is_file() and ".venv" not in p.parts)[:30]


def _claude_exe():
    for p in (Path.home() / ".local" / "bin" / "claude.exe", Path(os.environ["APPDATA"]) / "npm" / "claude.cmd"):
        if p.exists():
            return str(p)
    winget = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet"
    achados = list((winget / "Links").glob("claude.exe")) + list((winget / "Packages").glob("Anthropic.ClaudeCode_*/claude.exe"))
    return str(achados[0]) if achados else shutil.which("claude")


def desenvolver_com_claude(nome_do_projeto: str, pedido: str) -> str:
    """Pede ao Claude (IA programadora avancada) para DESENVOLVER de verdade um programa, aplicativo, ferramenta, site ou script
    (inclui transformar um projeto existente em aplicativo de desktop). No pedido, repita as palavras do usuario.
    Use para qualquer pedido de criar/desenvolver/programar algo. Roda em segundo plano e abre no Antigravity ao terminar."""
    import threading
    exe = _claude_exe()
    if not exe:
        return "O Claude Code ainda nao esta instalado neste PC."
    existente = _achar_pasta(nome_do_projeto)   # ja existe? melhora ele em vez de criar outra pasta
    if existente and existente.parent == PROJETOS:
        pasta, nome = existente, existente.name
        acao = ("Este projeto JA EXISTE nesta pasta: leia os arquivos atuais e MELHORE/CORRIJA o que existe "
                "conforme o pedido, sem recomecar do zero.")
    else:
        nome = "".join(c if c.isalnum() or c in "-_" else "-" for c in nome_do_projeto.lower()).strip("-") or "projeto"
        pasta = PROJETOS / nome
        pasta.mkdir(parents=True, exist_ok=True)
        acao = "Crie tudo nesta pasta."
    TAREFAS[nome] = {"status": "em andamento", "pasta": str(pasta), "pedido": pedido, "avisado": False}
    _salvar_tarefas()
    abrir_no_antigravity(str(pasta))   # abre ja, para acompanhar os arquivos aparecendo

    instrucao = (f"{pedido}\n\n{acao} Trabalhe de forma autonoma e sem fazer perguntas. Windows 11, placa AMD "
                 f"RX 9070 XT, Python 3.12 em C:\\Users\\{os.environ['USERNAME']}\\AppData\\Local\\Programs\\Python\\Python312\\python.exe. "
                 "OBRIGATORIO: rode e teste de verdade (inicie o programa, confira que abre sem erro e encerre). "
                 "Crie um iniciar.bat que use o caminho COMPLETO do python acima (no PATH, 'python' abre a Microsoft Store). "
                 "Se o pedido falar em APLICATIVO, APP ou PROGRAMA: entregue um app de desktop com JANELA PROPRIA (sem abrir o "
                 "navegador; ex.: pywebview com interface HTML, ou PySide6), dependencias num .venv dentro da pasta criado pelo "
                 "iniciar.bat na primeira vez, e um atalho .lnk na Area de Trabalho do usuario apontando para o iniciar.bat "
                 "(abrindo sem janela preta, via pythonw). "
                 "Inclua um README.md curto em portugues. "
                 "Termine com um resumo de 1 a 2 frases em portugues, falado (sem markdown).")
    threading.Thread(target=_rodar_claude, args=(nome, instrucao, pasta, []), daemon=True).start()
    return (f"O Claude comecou a desenvolver '{nome}'. A pasta {pasta} ja esta aberta no Antigravity; "
            "os arquivos vao aparecendo la. Aviso quando terminar.")


TRABALHO = Path(CONFIG.get("pasta_arquivos", RAIZ / "arquivos"))
# O Claude pode rodar comandos (no Windows eles passam pelo PowerShell) para testar o que cria,
# mas nunca apagar, formatar ou desligar o PC.
PROIBIDOS = ["Bash(rm:*)", "Bash(rmdir:*)", "Bash(del:*)", "Bash(format:*)", "Bash(shutdown:*)", "Bash(git push:*)",
             "PowerShell(Remove-Item:*)", "PowerShell(rm:*)", "PowerShell(del:*)", "PowerShell(rmdir:*)",
             "PowerShell(Format-Volume:*)", "PowerShell(Clear-Disk:*)", "PowerShell(Stop-Computer:*)",
             "PowerShell(Restart-Computer:*)", "PowerShell(shutdown:*)"]


def _rodar_claude(nome: str, instrucao: str, cwd: Path, extras: list[str]):
    exe = _claude_exe()
    pastas_usuario = [str(Path.home() / d) for d in ("Downloads", "Documents", "Desktop", "Pictures")]
    cmd = [exe, "-p", instrucao, "--permission-mode", "acceptEdits",
           "--allowedTools", "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Bash,PowerShell",
           "--disallowedTools", ",".join(PROIBIDOS)]
    for p in pastas_usuario + extras:
        cmd += ["--add-dir", p]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=1800)
        TAREFAS[nome]["status"] = "concluido" if r.returncode == 0 else "falhou"
        TAREFAS[nome]["resposta"] = (r.stdout or r.stderr).strip()[-1500:]
    except subprocess.TimeoutExpired:
        TAREFAS[nome]["status"] = "falhou"
        TAREFAS[nome]["resposta"] = "Demorou mais de 30 minutos e foi interrompido."
    _salvar_tarefas()


def pedir_ao_claude(tarefa: str) -> str:
    """Delega ao Claude (IA avancada e autonoma) QUALQUER tarefa complexa que as outras ferramentas nao resolvem:
    pesquisar a fundo na internet, responder perguntas dificeis, escrever textos/relatorios/planilhas, organizar
    pastas e arquivos (Downloads, Documentos, Area de Trabalho), analisar arquivos, resolver problemas no PC.
    Roda em segundo plano; o resultado e falado ao usuario quando terminar."""
    import threading
    if not _claude_exe():
        return "O Claude Code nao esta instalado neste PC."
    nome = "tarefa-" + datetime.datetime.now().strftime("%H%M%S")
    TAREFAS[nome] = {"status": "em andamento", "pasta": str(TRABALHO), "pedido": tarefa, "avisado": False, "tipo": "tarefa"}
    _salvar_tarefas()
    instrucao = (f"Pedido do usuario (feito por voz ao assistente Atlas): {tarefa}\n\n"
                 f"Execute de forma autonoma, sem fazer perguntas. Windows 11. Salve arquivos gerados em {TRABALHO}. "
                 "Nunca apague arquivos do usuario; para organizar, apenas mova. "
                 "Termine com um resumo de 1 a 3 frases em portugues, falado (sem markdown), dizendo o que fez e onde salvou.")
    threading.Thread(target=_rodar_claude, args=(nome, instrucao, TRABALHO, []), daemon=True).start()
    return "Passei a tarefa para o Claude. Ele esta trabalhando em segundo plano e eu aviso o resultado por voz."


def andamento_dos_projetos() -> str:
    """Informa o andamento dos projetos que o Claude esta desenvolvendo e quais arquivos ja foram criados."""
    if not TAREFAS:
        return "Nenhum projeto em desenvolvimento agora."
    partes = []
    for n, t in TAREFAS.items():
        arqs = arquivos_do_projeto(t["pasta"])
        partes.append(f"{n}: {t['status']}, {len(arqs)} arquivos ({', '.join(arqs[:6]) or 'nenhum ainda'})")
    return " | ".join(partes)


TODAS = [
    abrir_programa, abrir_site, pesquisar_na_web, tocar_no_youtube,
    criar_arquivo, listar_arquivos, ler_arquivo, abrir_pasta_de_arquivos,
    abrir_no_antigravity, data_e_hora, lembrar, status_do_pc, ajustar_voz, ler_noticias,
    desenvolver_com_claude, pedir_ao_claude, andamento_dos_projetos, executar_projeto, listar_projetos,
]
POR_NOME = {f.__name__: f for f in TODAS}
