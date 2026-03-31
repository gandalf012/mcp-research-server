import asyncio
import json
from typing import List, Optional

import nest_asyncio
from dotenv import load_dotenv
from anthropic import Anthropic
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

nest_asyncio.apply()
load_dotenv()


class MCP_ChatBot:
    def __init__(self):
        # FastMCP client (remplace ClientSession)
        self.session: Optional[Client] = None
        self.anthropic = Anthropic()
        self.available_tools: List[dict] = []

    async def process_query(self, query: str):
        messages = [{"role": "user", "content": query}]

        while True:
            response = self.anthropic.messages.create(
                max_tokens=2024,
                model="claude-sonnet-4-6",
                tools=self.available_tools,
                messages=messages,
                # Décommente si tu veux éviter les appels outils parallèles
                # tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            )

            # Toujours stocker le message assistant complet
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    print(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            # Si aucun outil n'est demandé, réponse finale terminée
            if not tool_uses:
                break

            tool_results = []

            for block in tool_uses:
                tool_name = block.name
                tool_args = block.input
                tool_id = block.id

                print(f"Calling tool {tool_name} with args {tool_args}")

                try:
                    # Appel via FastMCP client
                    result = await self.session.call_tool(tool_name, tool_args)

                    # Normalisation du contenu pour Anthropic
                    if hasattr(result, "content"):
                        raw_content = result.content
                    else:
                        raw_content = result

                    if isinstance(raw_content, str):
                        tool_content = raw_content
                    else:
                        try:
                            tool_content = json.dumps(raw_content, ensure_ascii=False)
                        except TypeError:
                            tool_content = str(raw_content)

                except Exception as e:
                    tool_content = json.dumps(
                        {"error": str(e), "tool_name": tool_name},
                        ensure_ascii=False
                    )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": tool_content
                })

            # IMPORTANT : tous les résultats outils ensemble dans le message suivant
            messages.append({
                "role": "user",
                "content": tool_results
            })

        return messages

    async def chat_loop(self):
        print("\nMCP Chatbot Started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if not query:
                    continue

                if query.lower() in {"quit", "exit"}:
                    print("Goodbye!")
                    break

                await self.process_query(query)
                print()

            except KeyboardInterrupt:
                print("\nInterrupted. Type 'quit' to exit.")
            except EOFError:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")

    async def connect_to_server_and_run(self):
        # Transport stdio FastMCP explicite
        transport = StdioTransport(
            command="uv",
            args=["run", "research_server.py"],
            env=None,
        )

        # auto_initialize=False pour rester proche de ta logique initiale
        client = Client(transport, auto_initialize=False)

        async with client:
            self.session = client

            # Équivalent logique de session.initialize()
            await client.initialize()

            # FastMCP retourne directement la liste des tools
            tools = await client.list_tools()

            print("\nConnected to server with tools:", [tool.name for tool in tools])

            self.available_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in tools
            ]

            await self.chat_loop()


async def main():
    chatbot = MCP_ChatBot()
    await chatbot.connect_to_server_and_run()

if __name__ == "__main__":
    asyncio.run(main())
