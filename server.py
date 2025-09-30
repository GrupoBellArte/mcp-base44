import os
import json
from flask import Flask, request, jsonify, Response, stream_with_context
import requests

app = Flask(__name__)

# === CONFIG ===
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("Defina a variável de ambiente API_KEY com a chave da Base44")

BASE_URL = "https://app.base44.com/api/apps/680d6ca95153f09fa29b4f1a/entities"

COMMON_HEADERS = {
    "api_key": API_KEY,
    "Content-Type": "application/json"
}

# Campos filtráveis por entidade
FILTERS = {
    "Client": [
        "name","company","email","phone","address","segment","tipo_estabelecimento",
        "status","assigned_to","classification","notes","observacoes_perfil",
        "created_date","last_contact","permitted_product_ids"
    ],
    "Interaction": [
        "client_id","date","type","description","outcome","next_steps","follow_up_date","client_name"
    ],
    "Task": [
        "title","description","due_date","priority","status","client_id","client_name","assigned_to"
    ],
    "Visit": [
        "title","type","client_id","client_name","description","start_date","end_date",
        "status","location","notes","assigned_to","post_visit_report","llm_processed_report",
        "attachments","participants","priority"
    ],
    "ContatoLoja": ["client_id","name","phone","email","role","notes"]
}

def build_params(entity: str, arguments: dict):
    allowed = set(FILTERS.get(entity, []))
    return {k: v for k, v in (arguments or {}).items() if k in allowed and v not in (None, "")}

# --- HTTP helpers (com logs de debug) ---
def b44_get(entity: str, params=None):
    url = f"{BASE_URL}/{entity}"
    r = requests.get(url, headers=COMMON_HEADERS, params=params or {})
    if r.status_code != 200:
        print("⚠️ Erro GET:", url, r.status_code, r.text)  # LOG detalhado
    r.raise_for_status()
    return r.json()

def b44_put(entity: str, entity_id: str, payload: dict):
    url = f"{BASE_URL}/{entity}/{entity_id}"
    r = requests.put(url, headers=COMMON_HEADERS, json=payload or {})
    if r.status_code not in (200, 201):
        print("⚠️ Erro PUT:", url, r.status_code, r.text)  # LOG detalhado
    r.raise_for_status()
    return r.json()

# --- Tools definitions (MCP) ---
TOOLS = [
    {"name": "consultarClientes","description": "Lista clientes com filtros opcionais.","inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Client"]}}},
    {"name": "atualizarCliente","description": "Atualiza um cliente.","inputSchema": {"type": "object","properties": {"id": {"type": "string"}, "dados": {"type": "object"}},"required": ["id", "dados"]}},
    {"name": "consultarInteracoes","description": "Lista interações.","inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Interaction"]}}},
    {"name": "atualizarInteracao","description": "Atualiza uma interação.","inputSchema": {"type": "object","properties": {"id": {"type": "string"}, "dados": {"type": "object"}},"required": ["id", "dados"]}},
    {"name": "consultarTarefas","description": "Lista tarefas.","inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Task"]}}},
    {"name": "atualizarTarefa","description": "Atualiza uma tarefa.","inputSchema": {"type": "object","properties": {"id": {"type": "string"}, "dados": {"type": "object"}},"required": ["id", "dados"]}},
    {"name": "consultarVisitas","description": "Lista visitas.","inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Visit"]}}},
    {"name": "atualizarVisita","description": "Atualiza uma visita.","inputSchema": {"type": "object","properties": {"id": {"type": "string"}, "dados": {"type": "object"}},"required": ["id", "dados"]}},
    {"name": "consultarContatosLoja","description": "Lista contatos de loja.","inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS.get("ContatoLoja", [])}}}
]

# --- Tools impl ---
def tool_consultar_clientes(arguments: dict): return b44_get("Client", build_params("Client", arguments))
def tool_atualizar_cliente(arguments: dict): return b44_put("Client", arguments["id"], arguments["dados"])
def tool_consultar_interacoes(arguments: dict): return b44_get("Interaction", build_params("Interaction", arguments))
def tool_atualizar_interacao(arguments: dict): return b44_put("Interaction", arguments["id"], arguments["dados"])
def tool_consultar_tarefas(arguments: dict): return b44_get("Task", build_params("Task", arguments))
def tool_atualizar_tarefa(arguments: dict): return b44_put("Task", arguments["id"], arguments["dados"])
def tool_consultar_visitas(arguments: dict): return b44_get("Visit", build_params("Visit", arguments))
def tool_atualizar_visita(arguments: dict): return b44_put("Visit", arguments["id"], arguments["dados"])
def tool_consultar_contatos_loja(arguments: dict): return b44_get("ContatoLoja", build_params("ContatoLoja", arguments))

TOOL_IMPL = {
    "consultarClientes": tool_consultar_clientes,
    "atualizarCliente": tool_atualizar_cliente,
    "consultarInteracoes": tool_consultar_interacoes,
    "atualizarInteracao": tool_atualizar_interacao,
    "consultarTarefas": tool_consultar_tarefas,
    "atualizarTarefa": tool_atualizar_tarefa,
    "consultarVisitas": tool_consultar_visitas,
    "atualizarVisita": tool_atualizar_visita,
    "consultarContatosLoja": tool_consultar_contatos_loja,
}

# === ENDPOINTS MCP ===
@app.route("/sse", methods=["GET", "POST"])
def sse():
    def generate():
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.headers.get("X-Forwarded-Host", request.host)
        base = f"{proto}://{host}"
        message_url = f"{base}/messages"
        yield "event: endpoint\n"
        yield f"data: {json.dumps({'type':'endpoint','message_url':message_url})}\n\n"
        yield "event: message\n"
        yield f"data: {json.dumps({'type':'server_info','tools':TOOLS})}\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.post("/messages")
def messages():
    payload = request.get_json(force=True, silent=False) or {}
    req_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    try:
        if method == "tools/list":
            return jsonify({"id": req_id, "result": {"tools": TOOLS}})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            result = TOOL_IMPL[name](arguments)
            return jsonify({"id": req_id, "result": {"content": result}})
        if method in ("ping", "health"):
            return jsonify({"id": req_id, "result": "ok"})
        return jsonify({"id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}), 400
    except Exception as e:
        # LOG detalhado do erro no Render
        print("⚠️ Erro interno:", str(e))
        return jsonify({"id": req_id, "error": {"code": 500, "message": str(e)}}), 500

@app.get("/")
def index():
    return "MCP server do CRM Base44 está no ar. Use /sse e /messages."

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
