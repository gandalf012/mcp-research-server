from dotenv import load_dotenv
from anthropic import Anthropic
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from contextlib import AsyncExitStack
import json
import asyncio
import nest_asyncio

nest_asyncio.apply()
load_dotenv()


class MCP_ChatBot:
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()

        self.available_tools = []
        self.available_prompts = []

        # maps:
        # - tool name -> client
        # - prompt name -> client
        # - resource uri -> client
        self.clients_by_name = {}
        self.clients = []

    async def connect_to_server(self, server_name, server_config):
        try:
            transport = StdioTransport(
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env"),
            )

            client = Client(transport, auto_initialize=False)
            client = await self.exit_stack.enter_async_context(client)
            await client.initialize()

            self.clients.append(client)

            # Tools
            tools = await client.list_tools()
            for tool in tools:
                self.clients_by_name[tool.name] = client
                self.available_tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                })

            # Prompts
            try:
                prompts = await client.list_prompts()
                for prompt in prompts:
                    self.clients_by_name[prompt.name] = client
                    self.available_prompts.append({
                        "name": prompt.name,
                        "description": getattr(prompt, "description", None),
                        "arguments": getattr(prompt, "arguments", None)
                    })
            except Exception:
                pass  # server may not support prompts

            # Resources
            try:
                resources = await client.list_resources()
                for resource in resources:
                    resource_uri = str(resource.uri)
                    self.clients_by_name[resource_uri] = client
            except Exception:
                pass  # server may not support resources

            print(f"\nConnected to {server_name} with tools:", [t.name for t in tools])

        except Exception as e:
            print(f"Error connecting to {server_name}: {e}")

    async def connect_to_servers(self):
        try:
            with open("server_config.json", "r") as file:
                data = json.load(file)

            servers = data.get("mcpServers", {})
            for server_name, server_config in servers.items():
                await self.connect_to_server(server_name, server_config)

        except Exception as e:
            print(f"Error loading server config: {e}")
            raise

    async def process_query(self, query):
        messages = [{"role": "user", "content": query}]

        while True:
            response = self.anthropic.messages.create(
                max_tokens=8096,
                model="claude-sonnet-4-6",
                tools=self.available_tools,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    print(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                break

            tool_results = []

            for block in tool_uses:
                tool_name = block.name
                tool_args = block.input
                tool_id = block.id

                print(f"Calling tool {tool_name} with args {tool_args}")

                client = self.clients_by_name.get(tool_name)
                if not client:
                    tool_content = json.dumps(
                        {"error": f"Tool '{tool_name}' not found"},
                        ensure_ascii=False
                    )
                else:
                    try:
                        result = await client.call_tool(tool_name, tool_args)

                        # FastMCP 3.x returns list[TextContent | ...]
                        if isinstance(result, list):
                            parts = [item.text if hasattr(item, "text") else str(item) for item in result]
                            tool_content = "\n".join(parts)
                        elif hasattr(result, "content"):
                            raw = result.content
                            tool_content = raw if isinstance(raw, str) else str(raw)
                        else:
                            tool_content = str(result)

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

            messages.append({
                "role": "user",
                "content": tool_results
            })

    async def get_resource(self, resource_uri):
        client = self.clients_by_name.get(resource_uri)

        if not client and resource_uri.startswith("papers://"):
            for name, c in self.clients_by_name.items():
                if isinstance(name, str) and name.startswith("papers://"):
                    client = c
                    break

        if not client:
            print(f"Resource '{resource_uri}' not found.")
            return

        try:
            result = await client.read_resource(resource_uri)

            print(f"\nResource: {resource_uri}")
            print("Content:")
            if isinstance(result, list):
                for item in result:
                    print(item.text if hasattr(item, "text") else str(item))
            elif hasattr(result, "contents") and result.contents:
                print(getattr(result.contents[0], "text", str(result.contents[0])))
            else:
                print(str(result))

        except Exception as e:
            print(f"Error: {e}")

    async def list_prompts(self):
        if not self.available_prompts:
            print("No prompts available.")
            return

        print("\nAvailable prompts:")
        for prompt in self.available_prompts:
            print(f"- {prompt['name']}: {prompt.get('description')}")
            if prompt.get("arguments"):
                print("  Arguments:")
                for arg in prompt["arguments"]:
                    arg_name = getattr(arg, "name", None) or arg.get("name", "")
                    print(f"    - {arg_name}")

    async def execute_prompt(self, prompt_name, args):
        client = self.clients_by_name.get(prompt_name)
        if not client:
            print(f"Prompt '{prompt_name}' not found.")
            return

        try:
            result = await client.get_prompt(prompt_name, arguments=args)

            if hasattr(result, "messages") and result.messages:
                content = result.messages[0].content

                if isinstance(content, str):
                    text = content
                elif hasattr(content, "text"):
                    text = content.text
                elif isinstance(content, list):
                    text = " ".join(
                        item.text if hasattr(item, "text") else str(item)
                        for item in content
                    )
                else:
                    text = str(content)

                print(f"\nExecuting prompt '{prompt_name}'...")
                await self.process_query(text)
            else:
                print("Prompt returned no messages.")

        except Exception as e:
            print(f"Error: {e}")

    async def chat_loop(self):
        print("\nMCP Chatbot Started!")
        print("Type your queries or 'quit' to exit.")
        print("Use @folders to see available topics")
        print("Use @<topic> to read a resource")
        print("Use /prompts to list available prompts")
        print("Use /prompt <name> <arg1=value1> to execute a prompt")

        while True:
            try:
                query = input("\nQuery: ").strip()
                if not query:
                    continue

                if query.lower() in {"quit", "exit"}:
                    break

                if query.startswith('@'):
                    topic = query[1:]
                    resource_uri = "papers://folders" if topic == "folders" else f"papers://{topic}"
                    await self.get_resource(resource_uri)
                    continue

                if query.startswith('/'):
                    parts = query.split()
                    command = parts[0].lower()

                    if command == '/prompts':
                        await self.list_prompts()
                    elif command == '/prompt':
                        if len(parts) < 2:
                            print("Usage: /prompt <name> <arg1=value1> <arg2=value2>")
                            continue

                        prompt_name = parts[1]
                        args = {}

                        for arg in parts[2:]:
                            if '=' in arg:
                                key, value = arg.split('=', 1)
                                args[key] = value

                        await self.execute_prompt(prompt_name, args)
                    else:
                        print(f"Unknown command: {command}")
                    continue

                await self.process_query(query)

            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        await self.exit_stack.aclose()


async def main():
    chatbot = MCP_ChatBot()
    try:
        await chatbot.connect_to_servers()
        await chatbot.chat_loop()
    finally:
        await chatbot.cleanup()


if __name__ == "__main__":
    asyncio.run(main())