# Model Context Protocol (MCP) — Notes d'apprentissage

> Expérience acquise via le repo `mcp/` — en tant que praticien agents/tools qui découvre MCP

---

## 1. Pourquoi MCP si on connaît déjà les agents et les tools ?

Si tu sais déjà construire des agents avec des tools, MCP te donne la même chose mais **standardisée et déconnectée du code de l'agent**. Au lieu de coder tes tools directement dans ton agent, tu les exposes via un **serveur MCP** — et n'importe quel client MCP (Claude Desktop, ton chatbot, Cursor, etc.) peut les consommer sans modification.

| Ce que tu faisais avant | Avec MCP |
|---|---|
| Tool défini dans le code de l'agent | Tool dans un serveur MCP indépendant |
| Couplé à un framework (LangChain, etc.) | Protocole universel, framework-agnostic |
| 1 agent = 1 ensemble de tools | N clients = 1 serveur partagé |
| Déploiement monolithique | Serveur MCP deployable séparément |

---

## 2. Architecture — Les trois rôles

```
┌─────────────────────────────────────────────────────┐
│                    MCP HOST                         │
│  (Claude Desktop, Cursor, ton chatbot custom...)    │
│                                                     │
│   ┌──────────────┐      ┌──────────────┐            │
│   │  MCP Client  │      │  MCP Client  │            │
│   │  (1 par srv) │      │  (1 par srv) │            │
└───┴──────┬───────┴──────┴──────┬───────┴────────────┘
           │ stdio / HTTP               │ stdio / HTTP
    ┌──────▼──────┐           ┌─────────▼──────┐
    │ MCP Server  │           │  MCP Server    │
    │ (local)     │           │  (remote)      │
    │ filesystem  │           │  research      │
    └─────────────┘           └────────────────┘
```

- **Host** : l'application AI (Claude Desktop, ton chatbot). Crée et gère les clients.
- **Client** : 1 connexion = 1 client. Parle au serveur via le protocole MCP.
- **Server** : expose des tools, resources, prompts. Peut tourner en local ou en remote.

---

## 3. Les deux couches du protocole

### Couche Transport (comment les messages circulent)

| Transport | Usage | Caractéristiques |
|---|---|---|
| **Stdio** | Local uniquement | stdin/stdout, zéro overhead réseau, idéal pour Claude Desktop |
| **Streamable HTTP** | Local + Remote | HTTP POST + SSE optionnel, auth Bearer/OAuth, multi-clients |
| **SSE** (legacy) | Déprécié | À éviter pour les nouveaux projets |

**Leçon apprise :** Pour Render (ou tout cloud), le serveur doit écouter sur `0.0.0.0` (pas `127.0.0.1`) et utiliser le port fourni par la variable `$PORT`.

### Couche Data (ce que transportent les messages)

JSON-RPC 2.0. Lifecycle : `initialize` → `list` → `call` → notifications.

---

## 4. Les primitives serveur

### Tools
Ce que tu connaissais déjà sous le nom "tools" dans tes agents. Fonctions exécutables exposées par le serveur.

```python
@mcp.tool()
def search_papers(topic: str, max_results: int = 5) -> List[str]:
    ...
```

### Resources
**Nouveau concept.** Données en lecture seule accessibles via une URI. Pensez-y comme des endpoints GET plutôt que des actions.

```python
@mcp.resource("papers://folders")        # URI statique
def get_folders() -> str: ...

@mcp.resource("papers://{topic}")        # URI avec paramètre
def get_topic_papers(topic: str) -> str: ...
```

Dans le chatbot : syntaxe `@topic` → `papers://topic` → appel `read_resource`.

### Prompts
**Nouveau concept.** Templates réutilisables qui génèrent des messages structurés. Le serveur expose des prompts que le client peut récupérer et envoyer au LLM.

```python
@mcp.prompt()
def generate_search_prompt(topic: str, num_papers: int = 5) -> str:
    return f"Search for {num_papers} papers about '{topic}'..."
```

Dans le chatbot : syntaxe `/prompt nom arg=valeur`.

---

## 5. Les primitives client

Ces primitives vont dans l'autre sens — le **serveur demande quelque chose au client** :

| Primitive | Description |
|---|---|
| **Sampling** | Le serveur demande une completion LLM au client (ex: résumer un doc) |
| **Elicitation** | Le serveur demande une confirmation ou info à l'utilisateur |
| **Logging** | Le serveur envoie des logs au client pour debug/monitoring |
| **Roots** | Le client déclare les répertoires accessibles au serveur |

**Leçon :** Claude Desktop ne supporte pas encore MCP Roots — d'où le message `Client does not support MCP Roots` au démarrage.

---

## 6. Construire un client MCP avec FastMCP

### Pattern multi-serveurs (ce qu'on a construit)

```python
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

# Serveur local → stdio
transport = StdioTransport(command="uv", args=["run", "server.py"])

# Serveur distant → HTTP
transport = StreamableHttpTransport(url="https://mon-serveur.onrender.com/mcp")

client = Client(transport, auto_initialize=False)
```

### Piège stdio sur Mac (Claude Desktop)
Claude Desktop n'hérite pas du `$PATH` shell. Les binaires installés dans `~/.local/bin` (uv, uvx) ne sont pas trouvés. **Toujours utiliser le chemin absolu** dans `claude_desktop_config.json`.

### Piège npm + stdio
`npx -y` exécute `npm install` au démarrage. Les messages npm (`added 40 packages`, `run npm fund`, `found 0 vulnerabilities`) s'écrivent sur stdout — le canal MCP. Résultat : erreurs `Failed to parse JSONRPC message`.

**Fix :**
```json
"env": {
    "npm_config_loglevel": "silent",
    "npm_config_fund": "false",
    "npm_config_audit": "false"
}
```

---

## 7. Configurations selon l'environnement

### server_config.json (chatbot local)

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
      "env": { "npm_config_loglevel": "silent", "npm_config_fund": "false", "npm_config_audit": "false" }
    },
    "research": {
      "url": "https://mcp-research-server-1.onrender.com/mcp"
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    }
  }
}
```

### claude_desktop_config.json
Même structure, mais les binaires doivent être en chemin absolu :
```json
"command": "/Users/arnauld/.local/bin/uv"
```

### research_server.py (déployé sur Render)
```python
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    mcp.run(transport="http", host="0.0.0.0", port=port)
```

---

## 8. Commandes pour explorer un serveur MCP

### Lancer un serveur

```bash
# Mode stdio (défaut) — pour inspector ou Claude Desktop
uv run research_server.py

# Mode HTTP local — pour tester en remote ou inspector HTTP
uv run research_server.py   # avec transport="http" dans run()

# Via FastMCP CLI
fastmcp run research_server.py                          # stdio
fastmcp run research_server.py --transport http         # HTTP
```

### Inspecter avec le MCP Inspector

```bash
# ── Option A : stdio, tout-en-un ─────────────────────────────────────────
npx @modelcontextprotocol/inspector \
  uv --directory /chemin/vers/mcp_project run research_server.py
# → ouvre l'UI, le serveur est spawné automatiquement

# ── Option B : HTTP, deux terminaux ──────────────────────────────────────
# Terminal 1 — serveur
uv run research_server.py

# Terminal 2 — inspector standalone
npx @modelcontextprotocol/inspector
# Dans l'UI : Transport = Streamable HTTP
#             URL      = http://127.0.0.1:8081/mcp

# ── Option C : FastMCP dev mode (équivalent Option A) ────────────────────
fastmcp dev research_server.py
```

### Explorer via curl (serveur HTTP actif)

```bash
BASE="http://127.0.0.1:8081/mcp"

# Initialiser la session (obligatoire en premier)
curl -s -X POST $BASE \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"0.1"}}}'

# Lister les tools
curl -s -X POST $BASE \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Lister les resources
curl -s -X POST $BASE \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"resources/list","params":{}}'

# Lister les prompts
curl -s -X POST $BASE \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"prompts/list","params":{}}'

# Appeler un tool
curl -s -X POST $BASE \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"search_papers","arguments":{"topic":"deep learning","max_results":3}}}'

# Lire une resource
curl -s -X POST $BASE \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":5,"method":"resources/read","params":{"uri":"papers://folders"}}'
```

### Commandes du chatbot (mcp_chatbot_v2.py)

```
@folders               → liste les topics disponibles (resource papers://folders)
@<topic>               → affiche les papers d'un topic (resource papers://<topic>)
/prompts               → liste tous les prompts disponibles
/prompt <nom> <k=v>    → exécute un prompt avec des arguments
quit / exit            → quitte le chatbot
```

### Débugger Claude Desktop

```bash
# Logs MCP en temps réel
tail -f ~/Library/Logs/Claude/mcp-server-research.log
tail -f ~/Library/Logs/Claude/mcp-server-filesystem.log
tail -f ~/Library/Logs/Claude/mcp-server-fetch.log

# Voir tous les logs MCP
ls ~/Library/Logs/Claude/
```

### Installer un serveur dans Claude Desktop via FastMCP CLI

```bash
# Ajoute automatiquement l'entrée dans claude_desktop_config.json
fastmcp install research_server.py --name research
```

---

## 9. FastMCP — Particularités v3.x

| Élément | Avant (v2) | v3.x |
|---|---|---|
| `FastMCP(port=...)` | Accepté | **Erreur** — passer à `run()` |
| Transport | `"streamable-http"` | `"http"` |
| `call_tool()` retourne | objet structuré | `list[TextContent]` → extraire `.text` |
| `max_tokens` par défaut | 2024 (trop petit) | Mettre **8096** minimum |

---

## 10. Architecture de ce qu'on a construit

```
Claude Desktop / mcp_chatbot_v2.py (Host)
    │
    ├── MCP Client ──(stdio)──► filesystem server  (npx, local)
    ├── MCP Client ──(stdio)──► fetch server       (uvx, local)
    └── MCP Client ──(HTTP)───► research server    (Render, remote)
                                    │
                                    ├── tool: search_papers
                                    ├── tool: extract_info
                                    ├── resource: papers://folders
                                    ├── resource: papers://{topic}
                                    └── prompt: generate_search_prompt
```

---

## Ressources

- Spec MCP : https://modelcontextprotocol.io/docs/concepts/architecture
- FastMCP docs : https://gofastmcp.com
- MCP Inspector : https://github.com/modelcontextprotocol/inspector
- Debugging Claude Desktop : `~/Library/Logs/Claude/mcp*.log`
