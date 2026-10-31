"""Atlas: servidor local que ouve (Whisper), pensa (Ollama) e age (ferramentas.py)."""
import datetime
import re
import sys
from pathlib import Path

# Sem janela (pythonw) nao existe stdout/stderr e o uvicorn quebra; manda tudo pra um log.
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(Path(__file__).with_name("atlas.log"), "a", encoding="utf-8", buffering=1)

import numpy as np
import ollama
import uvicorn
from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse, Response
from faster_whisper import WhisperModel
from pydantic import BaseModel

import ferramentas
import extras
import voz_dono

BASE = Path(__file__).parent
CONFIG = ferramentas.CONFIG
app = FastAPI()
# Frase de exemplo que ajuda o Whisper com nomes proprios; personalize em config.json ("dica_voz").
DICA_VOZ = CONFIG.get("dica_voz", f"{CONFIG['nome']}, abre o Chrome. {CONFIG['nome']}, como está o PC? "
                                  "Antigravity, GitHub, YouTube.")
URL_WHISPER_GPU = "http://127.0.0.1:7778/inference"   # whisper.cpp compilado com Vulkan (placa AMD)
_cpu_whisper = None


def cpu_whisper() -> WhisperModel:
    """Reserva: Whisper no processador, carregado so se a GPU falhar."""
    global _cpu_whisper
    if _cpu_whisper is None:
        _cpu_whisper = WhisperModel(CONFIG["whisper"], device="cpu", compute_type="int8", cpu_threads=8)
    return _cpu_whisper


def transcrever_gpu(pcm: np.ndarray) -> str | None:
    """Transcreve na placa de video via whisper-server. None se o servidor nao responder."""
    import io
    import json as _json
    import urllib.request
    import wave
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
    campos = {"language": "pt", "response_format": "json", "temperature": "0", "prompt": DICA_VOZ}
    b = "atlasfronteira"
    corpo = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in campos.items())
    corpo += f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    corpo += wav.getvalue() + f"\r\n--{b}--\r\n".encode()
    try:
        req = urllib.request.Request(URL_WHISPER_GPU, corpo, {"Content-Type": f"multipart/form-data; boundary={b}"})
        return _json.loads(urllib.request.urlopen(req, timeout=30).read()).get("text", "").strip()
    except Exception:
        return None
# Memoria da conversa: sobrevive a reinicios (so falas do usuario e do Atlas, sem chamadas de ferramenta)
ARQ_HISTORICO = Path(__file__).with_name("historico.json")
# A conversa anterior entra so como CONTEXTO no prompt (nao como falas): falas sem as acoes registradas
# faziam o modelo imitar respostas "Pronto, fechei" sem chamar ferramenta nenhuma.
_anteriores = (__import__("json").loads(ARQ_HISTORICO.read_text(encoding="utf-8")) if ARQ_HISTORICO.exists() else [])
CONVERSA_ANTERIOR = "\n".join(("Usuario: " if m["role"] == "user" else "Atlas: ") + m["content"][:160]
                               for m in _anteriores[-10:]) or "(nenhuma)"
historico: list[dict] = []


def salvar_historico():
    import json
    falas = [{"role": m["role"], "content": m["content"]} for m in
             (h if isinstance(h, dict) else {"role": h.role, "content": h.content or ""} for h in historico)
             if m["role"] in ("user", "assistant") and m["content"]]
    ARQ_HISTORICO.write_text(json.dumps(falas[-30:], ensure_ascii=False, indent=1), encoding="utf-8")
# Pedido que exige executar algo: se o modelo responder sem chamar ferramenta, ele esta "fingindo"
PEDIDO_DE_ACAO = re.compile(r"(abr[ea]|fech[ea]|deslig[ua]e?|reinici[ae]|suspend[ae]|hibern[ae]|bloquei[ae]|cri[ae]|"
                            r"toc[ae]|pausa|aument[ae]|diminu[ai]|abaix[ae]|lembr[ae]|desenvolv[ae]|pesquis[ae]|"
                            r"organiz[ae]|execut[ae]|rod[ae]|inici[ae]|cancel[ae]|salv[ae]|escrev[ae])", re.I)
PROMESSA = re.compile(r"\b(vou|irei|estou (fazendo|criando|desenvolvendo|ajustando|abrindo|verificando)|j[aá] estou|um momento|aguarde)\b", re.I)
ultima_imagem: bytes | None = None
FANTASMA = re.compile(r"((tchau|obrigad[oa]|valeu|t[aá]|ok|h[aã]+|hum+|legendas? .*|inscreva-se.*|amara\.org.*)[ ,.!]*)+")
# Frases que o Whisper "inventa" a partir de legendas de videos; se aparecerem, o trecho inteiro e descartado
FANTASMA_EM_QUALQUER_LUGAR = re.compile(
    r"acesse o nosso site|fema\.org|www\.|\.com\.br|legendas? (pela|por)|amara\.org|obrigad[oa] por assistir|"
    r"inscreva-se|deixe (seu|o seu) like|ative o sininho|at[eé] o pr[oó]ximo v[ií]deo|tradu[cç][aã]o e legendas", re.I)


def olhar_pela_camera(pergunta: str = "Descreva o que voce ve.") -> str:
    """Olha pela webcam e descreve o que esta vendo (a pessoa, o ambiente, um objeto mostrado)."""
    if not ultima_imagem:
        return "A camera esta desligada. Peca para o usuario ligar a camera na interface."
    r = ollama.chat(model=CONFIG["modelo_visao"], keep_alive=0, messages=[{
        "role": "user", "images": [ultima_imagem],
        "content": f"Voce e os olhos de um assistente. Responda em portugues, em 1 a 2 frases. {pergunta}"}])
    return r.message.content


ferramentas.TODAS.append(olhar_pela_camera)
ferramentas.POR_NOME["olhar_pela_camera"] = olhar_pela_camera
for _f in extras.TODAS:
    ferramentas.TODAS.append(_f)
    ferramentas.POR_NOME[_f.__name__] = _f


def sistema() -> dict:
    memoria = "\n".join(f"- {m}" for m in ferramentas.carregar_memoria()) or "- (nada ainda)"
    agora = datetime.datetime.now()
    periodo = "madrugada" if agora.hour < 5 else "manha" if agora.hour < 12 else "tarde" if agora.hour < 18 else "noite"
    return {"role": "system", "content": f"""Voce e {CONFIG['nome']}, o assistente pessoal de IA do {CONFIG['usuario']}, \
no estilo de um mordomo digital elegante, inteligente e levemente bem-humorado.
Agora sao {agora:%H:%M} de {agora:%d/%m/%Y} ({periodo}). Use SEMPRE esta hora, nunca uma hora dita antes na conversa, \
e cumprimente de acordo (bom dia, boa tarde, boa noite).
Fale SEMPRE em portugues do Brasil. Suas respostas serao faladas em voz alta: seja curto e natural \
(1 a 3 frases), sem markdown, sem listas, sem emojis.
Voce TEM ferramentas reais. Quando o pedido precisar de uma acao ou informacao (hora, abrir programa, site, \
pesquisa, arquivo, camera), CHAME A FERRAMENTA IMEDIATAMENTE, sem anunciar. Nunca responda "vou verificar" ou \
"vou fazer": faca e depois diga o resultado. Nunca invente que fez algo que nao fez.
Para CRIAR, DESENVOLVER ou PROGRAMAR qualquer ferramenta, programa, site ou script, use desenvolver_com_claude \
(o Claude e o engenheiro que constroi; voce coordena). Para saber como o PC esta, use status_do_pc. Para noticias, manchetes ou "o que esta acontecendo", use \
ler_noticias e conte as principais manchetes de forma resumida. \
Para mudar sua voz, use ajustar_voz. Para QUALQUER outro pedido que exija pesquisa, raciocinio, escrever algo longo, organizar ou analisar arquivos, ou que nenhuma ferramenta resolva, use pedir_ao_claude passando o pedido completo. Nunca diga que nao consegue: delegue ao Claude. So abra sites quando o usuario pedir explicitamente para abrir um site.
Voce TEM permissao para desligar, reiniciar, suspender, hibernar o PC e fechar programas via controlar_pc: \
quando o usuario pedir claramente, EXECUTE (nunca diga que nao tem permissao) e avise que ele pode dizer 'cancela'. \
Lembretes/alarmes ("me lembra", "me avisa", "desperta"): criar_lembrete. Volume, musica, pausar, bloquear a tela, reiniciar o computador ou cancelar o reinicio: controlar_pc. \
Para testar se o PC esta estavel (travamentos, erros, desligamentos inesperados): teste_de_estabilidade. \
Sobre algo NA TELA do computador ("esse erro", "o que esta aberto", "le isso pra mim"): olhar_a_tela. \
Quando o usuario contar algo pessoal ou importante (preferencias, nomes, empresa, rotina), guarde com lembrar.
Voce tem olhos: quando perguntarem o que voce ve, como o usuario esta, ou pedirem para olhar algo, use olhar_pela_camera.
Quando pedirem um texto (post, legenda, roteiro), escreva o texto completo com criar_arquivo e diga so um resumo curto.
PROJETOS que o Claude ja criou: {ferramentas.listar_projetos()}
- Para ABRIR, RODAR, USAR ou INICIAR um projeto/plataforma, use executar_projeto (abre o programa funcionando).
- So use abrir_no_antigravity quando pedirem para ver ou editar o CODIGO.
- Para MELHORAR, CORRIGIR ou ADICIONAR algo a um projeto existente, use desenvolver_com_claude com o MESMO nome do projeto.
O que voce sabe sobre o {CONFIG['usuario']}:
{memoria}"""}


class Mensagem(BaseModel):
    texto: str


@app.get("/")
def interface():
    return FileResponse(BASE / "interface.html", headers={"Cache-Control": "no-store"})


@app.post("/ouvir")
async def ouvir(audio: UploadFile):
    # a interface envia PCM float32 mono 16 kHz, sem precisar de decodificador
    pcm = np.frombuffer(await audio.read(), dtype=np.float32)
    sim = voz_dono.similaridade(pcm)
    if sim < voz_dono.LIMIAR:
        return {"texto": "", "dono": False, "similaridade": round(sim, 2)}
    texto = transcrever_gpu(pcm)
    if texto is None:  # servidor na GPU fora do ar: usa o Whisper no processador
        segmentos, _ = cpu_whisper().transcribe(pcm, language="pt", vad_filter=True, beam_size=5,
                                                condition_on_previous_text=False, initial_prompt=DICA_VOZ)
        # Whisper "inventa" frases em silencio/ruido: descarta trechos incertos
        texto = " ".join(s.text.strip() for s in segmentos if s.no_speech_prob < 0.5 and s.avg_logprob > -0.9).strip()
    if FANTASMA.fullmatch(texto.lower().strip(" .,!?")) or FANTASMA_EM_QUALQUER_LUGAR.search(texto):
        texto = ""
    return {"texto": texto, "dono": True, "similaridade": round(sim, 2)}


@app.post("/voz/cadastrar")
async def voz_cadastrar(audio: UploadFile, ultima: bool = False):
    pcm = np.frombuffer(await audio.read(), dtype=np.float32)
    return {"amostras": voz_dono.adicionar_amostra(pcm, ultima), "cadastrado": voz_dono.cadastrado()}


@app.post("/voz/apagar")
def voz_apagar():
    voz_dono.apagar()
    return {"ok": True}


@app.post("/camera")
async def camera(foto: UploadFile):
    global ultima_imagem
    ultima_imagem = await foto.read()
    return {"ok": True}


@app.post("/camera/desligar")
def camera_desligar():
    global ultima_imagem
    ultima_imagem = None
    return {"ok": True}


@app.post("/conversar")
def conversar(msg: Mensagem):
    historico.append({"role": "user", "content": msg.texto})
    extras.ultima_fala = msg.texto
    del historico[:-20]
    acoes = []
    cobrado = False
    for _ in range(6):
        r = ollama.chat(model=CONFIG["modelo"], messages=[sistema(), *historico],
                        tools=ferramentas.TODAS, think=False, keep_alive=-1)
        if not r.message.tool_calls:
            # promessa sem acao ("vou fazer", "estou desenvolvendo")? cobra uma vez antes de responder
            if not cobrado and not acoes and (PROMESSA.search(r.message.content or "") or PEDIDO_DE_ACAO.search(msg.texto)):
                cobrado = True
                historico.append({"role": "system", "content": "Voce prometeu uma acao mas nao chamou nenhuma ferramenta. "
                                  "Chame a ferramenta adequada AGORA. Se nenhuma ferramenta serve, diga honestamente que ainda nao consegue fazer isso."})
                continue
            if not (acoes == [] and PEDIDO_DE_ACAO.search(msg.texto)):
                historico.append(r.message)   # resposta "fingida" (acao sem ferramenta) nao entra: contaminaria as proximas
            break
        historico.append(r.message)
        for chamada in r.message.tool_calls:
            func = ferramentas.POR_NOME.get(chamada.function.name)
            try:
                resultado = func(**chamada.function.arguments) if func else "Ferramenta desconhecida."
            except Exception as e:
                resultado = f"Erro: {e}"
            acoes.append({"acao": chamada.function.name, "resultado": resultado})
            historico.append({"role": "tool", "content": str(resultado), "tool_name": chamada.function.name})
    resposta = re.sub(r"<think>.*?</think>", "", r.message.content or "", flags=re.S).strip()
    # Tarefa entregue ao Claude: o modelo local nao pode "adiantar" a resposta (ele inventaria). So confirma.
    delegou = [a for a in acoes if a["acao"] in ("pedir_ao_claude", "desenvolver_com_claude")]
    if delegou:
        resposta = "Certo. Passei para o Claude, ele já está trabalhando nisso. Te aviso quando terminar."
    salvar_historico()
    return {"resposta": resposta or "Feito.", "acoes": acoes}


@app.post("/falar")
async def falar(msg: Mensagem):
    import edge_tts
    audio = b""
    async for parte in edge_tts.Communicate(msg.texto, CONFIG.get("voz", "pt-BR-AntonioNeural"),
                                            rate="+5%", pitch="-4Hz").stream():
        if parte["type"] == "audio":
            audio += parte["data"]
    return Response(audio, media_type="audio/mpeg", headers={"X-Robotico": str(CONFIG.get("robotico", 0.25))})


@app.get("/projetos")
def projetos():
    """Andamento dos projetos do Claude; 'novos_concluidos' sao avisados uma unica vez."""
    lista, novos = [], []
    for nome, t in ferramentas.TAREFAS.items():
        lista.append({"nome": nome, "status": t["status"], "arquivos": ferramentas.arquivos_do_projeto(t["pasta"])})
        if t["status"] in ("concluido", "falhou") and not t.get("avisado"):
            t["avisado"] = True
            novos.append({"nome": nome, "status": t["status"], "tipo": t.get("tipo", "projeto"),
                          "resposta": t.get("resposta", "")[-400:]})
    if novos:
        ferramentas._salvar_tarefas()
    return {"projetos": lista[-5:], "novos_concluidos": novos, "lembretes": extras.lembretes_vencidos()}


@app.get("/config")
def config():
    return {"nome": CONFIG["nome"], "usuario": CONFIG["usuario"], "modelo": CONFIG["modelo"],
            "voz_cadastrada": voz_dono.cadastrado()}


@app.on_event("startup")
def aquecer():
    """Carrega o cerebro na GPU e roda o reconhecedor uma vez, para a 1a conversa ja ser rapida."""
    import threading

    def _aquecer():
        try:
            ollama.chat(model=CONFIG["modelo"], messages=[{"role": "user", "content": "oi"}], think=False, keep_alive=-1)
            if transcrever_gpu(np.zeros(16000, dtype=np.float32)) is None:
                list(cpu_whisper().transcribe(np.zeros(16000, dtype=np.float32), language="pt")[0])
        except Exception as e:
            print("aquecimento falhou:", e)
    threading.Thread(target=_aquecer, daemon=True).start()
    extras.checar_pos_reinicio()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=CONFIG["porta"], log_level="warning")
