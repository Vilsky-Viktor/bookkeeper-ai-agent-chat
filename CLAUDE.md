# Rules for this repo

1. **English only in comments and prompts.** Write every code comment, docstring and
   LLM prompt in English. Don't quote or cite other languages in them: examples of
   words, phrases or receipt text in another language aren't allowed either.
   User-facing translations belong only in `web/src/lib/i18n/locales/`.

2. **An empty line before each block and each return.** In generated code, put an
   empty line before every block statement (`if`, `for`, `while`, `try`, `with`,
   `switch`, nested functions and similar) and before every `return`. The exception
   is when that statement is the first line of its enclosing block; formatters
   remove a blank line there anyway.

3. **At most 300 lines per file.** When a file would grow past 300 lines, split it
   along the lines of rule 4 before adding more.

4. **Separate logical modules.** Keep each kind of code in its own file for
   readability and maintainability: schemas, models, types, helper functions,
   prompts and constants each get their own module. Don't mix them with the logic
   that uses them.

5. **Keep code as simple as possible.** Strictly avoid overcomplicating and
   overengineering: no abstractions, layers, options or generalizations that the
   current need doesn't require. Choose the most direct solution that works.
