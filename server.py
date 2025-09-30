import os
import json
from flask import Flask, request, jsonify, Response, stream_with_context
import requests

app = Flask(__name__)

# ========= CONFIG =========
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("Defina a variável de ambiente API_KEY com a chave da Base44 (valor puro, sem aspas/linhas extras)")

# Base da sua app no Base44
BASE_URL = "https://app.base44.com/api/apps/680d6ca95153f09fa29b4f1a/entities"

COMMON_HEADERS = {
    "api_key": API_KEY,
    "Content-Type": "application/json",
}

# ========= SCHEMAS =========
FILTERS = {
    "Client": [
        "name","company","email","phone","address","segment","tipo_estabelecimento",
        "status","assigned_to","classification","notes","observacoes_perfil",
        "created_date","last_contact","permitted_product_ids",
    ],
    "Interaction": [
        "client_id","date","type","description","outcome","next_steps",
        "follow_up_date","client_name",
    ],
    "Task": [
        "title","description","due_date","priority","status",
        "client_id","client_name","assigned_to",
    ],
    "Visit": [
        "title","type","client_id","client_name","description","start_date","end_date",
        "status","location","notes","assigned_to","post_visit_report","llm_processed_report",
        "attachments","participants","priority",
    ],
    "ContatoLoja": ["client_id","name","phone","email","role","notes"],
}

def build_params(entity: str, arguments: dict):
    allowed = set(FILTERS.get(entity, []))
    return {
        k: v for k, v in (arguments or {}).items()
        if k in allowed and v not in (None, "")
    }

# ========= HELPERS =========
def b44_get(entity: str, params=None):
    url = f"{BASE_URL}/{entity}"
    r = requests.get(url, headers=COMMON_HEADERS, params=params or {})
    if r.status_code != 200:
        print("⚠️ Erro GET:", url, r.status_code, r.text)
    r.raise_for_status()
    return r.json()

def b44_put(entity: str, entity_id: str, payload: dict):
    url = f"{BASE_URL}/{entity}/{entity_id}"
    r = requests.put(url, headers=COMMON_HEADERS, json=payload or {})
    if r.status_code not in (200, 201):
        print("⚠️ Erro PUT:", url, r.status_code, r.text)
    r.raise_for_status()
    return r.json()

# ========= TOOLS =========
TOOLS = [
    {
        "name": "consultarClientes",
        "description": "Lista clientes com filtros opcionais.",
        "inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Client"]}},
    },
    {
        "name": "atualizarCliente",
        "description": "Atualiza um cliente (use o _id do cliente).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "dados": {"type": "object"}},
            "required": ["id","dados"],
        },
    },
    {
        "name": "consultarInteracoes",
        "description": "Lista interações.",
        "inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Interaction"]}},
    },
    {
        "name": "atualizarInteracao",
        "description": "Atualiza uma interação (use o _id da interação).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "dados": {"type": "object"}},
            "required": ["id","dados"],
        },
    },
    {
        "name": "consultarTarefas",
        "description": "Lista tarefas.",
        "inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Task"]}},
    },
    {
        "name": "atualizarTarefa",
        "description": "Atualiza uma tarefa (use o _id da tarefa).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "dados": {"type": "object"}},
            "required": ["id","dados"],
        },
    },
    {
        "name": "consultarVisitas",
        "description": "Lista visitas.",
        "inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS["Visit"]}},
    },
    {
        "name": "atualizarVisita",
        "description": "Atualiza uma visita (use o _id da visita).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "dados": {"type": "object"}},
            "required": ["id","dados"],
        },
    },
    {
        "name": "consultarContatosLoja",
        "description": "Lista contatos de loja.",
        "inputSchema": {"type": "object","properties": {k: {"type": "string"} for k in FILTERS.get("ContatoLoja", [])}},
    },
]

# ========= IMPLEMENTAÇÕES =========
def tool_consultar_clientes(args):       return b44_get("Client",      build_params("Client", args))
def tool_atualizar_cliente(args):        return b44_put("Client",      args["id"], args["dados"])
def tool_consultar_interacoes(args):     return b44_get("Interaction", build_params("Interaction", args))
def tool_atualizar_interacao(args):      return b44_put("Interaction", args["id"], args["dados"])
def tool_consultar_tarefas(args):        return b44_get("Task",        build_params("Task", args))
def tool_atualizar_tarefa(args):         return b44_put("Task",        args["id"], args["dados"])
def tool_consultar_visitas(args):        return b44_get("Visit",       build_params("Visit", args))
def tool_atualizar_visita(args):         return b44_put("Visit",       args["id"], args["dados"])
def tool_consultar_contatos_loja(args):  return b44_get("ContatoLoja", build_params("ContatoLoja", args))

TOOL_IMPL = {
    "consultarClientes":       tool_consultar_clientes,
    "atualizarCliente":        tool_atualizar_cliente,
    "consultarInteracoes":     tool_consultar_interacoes,
    "atualizarInteracao":      tool_atualizar_interacao,
    "consultarTarefas":        tool_consultar_tarefas,
    "atualizarTarefa":         tool_atualizar_tarefa,
    "consultarVisitas":        tool_consultar_visitas,
    "atualizarVisita":         tool_atualizar_visita,
    "consultarContatosLoja":   tool_consultar_contatos_loja,
}

# ========= ENDPOINTS MCP =========
@app.route("/sse", methods=["GET","POST"])
def sse():
    try:
        print("🔌 Nova conexão recebida em /sse")
        def generate():
            proto = request.headers.get("X-Forwarded-Proto", request.scheme)
            host  = request.headers.get("X-Forwarded-Host",  request.host)
            base  = f"{proto}://{host}"
            message_url = f"{base}/messages"

            print("📡 Enviando endpoint e tools para o cliente MCP...")
            yield "event: endpoint\n"
            yield f"data: {json.dumps({'type':'endpoint','message_url':message_url})}\n\n"

            yield "event: message\n"
            yield f"data: {json.dumps({'type':'server_info','tools':TOOLS})}\n\n"
        return Response(stream_with_context(generate()), mimetype="text/event-stream")
    except Exception as e:
        print("❌ Erro no /sse:", str(e))
        return jsonify({"error": str(e)}), 500

@app.post("/messages")
def messages():
    payload = request.get_json(force=True, silent=False) or {}
    req_id  = payload.get("id")
    method  = payload.get("method")
    params  = payload.get("params") or {}

    try:
        # 1) Listagem de ferramentas
        if method == "tools/list":
            return jsonify({
                "id": req_id,
                "result": {
                    "tools": TOOLS
                }
            })

        # 2) Chamada de ferramenta
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}

            if name not in TOOL_IMPL:
                return jsonify({
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{name}' não encontrada"
                    }
                }), 400

            result = TOOL_IMPL[name](arguments)

            return jsonify({
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "json",
                            "data": result
                        }
                    ]
                }
            })

        # 3) Ping / Health
        if method in ("ping", "health"):
            return jsonify({"id": req_id, "result": "ok"})

        # 4) Método desconhecido
        return jsonify({
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method '{method}' não suportado"
            }
        }), 400

    except Exception as e:
        print("❌ Erro interno em /messages:", str(e))
        return jsonify({
            "id": req_id,
            "error": {
                "code": 500,
                "message": str(e)
            }
        }), 500

@app.get("/")
def index():
    return "MCP server do CRM Base44 está no ar. Use /sse e /messages."
    
if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
