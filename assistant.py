from commands import handle_command

print("🤖 AI Terminal Assistant Started")
print("Type 'help' to see available commands")
print("Type 'exit' to quit\n")

while True:
    user_input = input(">> ").strip()

    if user_input in ["exit", "quit"]:
        print("Goodbye 👋")
        break

    handle_command(user_input)
