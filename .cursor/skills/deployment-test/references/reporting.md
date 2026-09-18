# Reporting


Keep the report concise and evidence-based:

- State whether the deployment is currently usable.
- Identify the first real error and the latest repeated error.
- Name the affected container(s).
- Include the relevant exception class and top stack frame.
- Distinguish harmless scanner traffic/404s from PsyNet/Dallinger failures.
- If a code fix is needed, name the likely file/function and propose the minimal regression test.
- Mention the detailed Markdown log-analysis file path created after completion.

Do not ask the user to re-paste logs that are already accessible in Dozzle unless browser login or permissions block access.
