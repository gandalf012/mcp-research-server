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

## 8. Outils de développement

### MCP Inspector

```bash
# Option 1 — stdio, tout-en-un (recommandé pour développement)
npx @modelcontextprotocol/inspector uv --directory /path/to/project run server.py

# Option 2 — HTTP, deux terminaux
# Terminal 1 : uv run research_server.py
# Terminal 2 : npx @modelcontextprotocol/inspector
# Dans l'UI : Transport=Streamable HTTP, URL=http://127.0.0.1:8081/mcp
```

Permet de tester tools, resources et prompts individuellement sans passer par le chatbot.

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
