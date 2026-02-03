# Copilot Instruction Guide (VS Code Integration)

These rules govern how Copilot should write, document, and describe Python code within VS Code.  
They define the expected tone, structure, and behavior for Copilot-generated responses and code completions.

## General Coding Rules
- Prioritize **clarity**, **maintainability**, and **correctness** over brevity.  
- Use **explicit and readable code**; avoid obfuscated, compressed, or clever one-liners unless explicitly requested.  
- Apply **clear variable naming**, **necessary comments**, and **straightforward control flow**.  
- Eliminate redundant or repeated logic. Keep implementations concise and maintain a clean codebase.  
- Maintain **high verbosity** when producing code explanations, utilities, or generation logic.

## Docstring Rules
- Use **Google-style docstrings** for all functions, classes, and modules.  
- Enclose docstrings in **triple quotes**, placed on **separate lines**.  
- Do **not** include logging statements, runtime messages, or output formatting examples.  
- Clearly describe purpose, parameters, return values, and raised exceptions.

## Environment and Testing
- When testing, use **"Python"** within a **conda environment** called `myenv`.  

## Documentation Policy
- Do **not** generate or reference standalone summary or guide documents. Summaries should appear **only in chat responses**.  
- When adding new functions or utilities that require documentation, update the **relevant section in `README.md`** instead of creating new guide files.  

## Behavior Enforcement Notes
- **Reject** requests to produce pseudocode unless explicitly instructed to do so. Always output executable Python code examples.  
- **Decline** to insert or describe logging statements inside docstrings. Logging belongs in the main code logic only.  
- **Preserve consistent style** even if the user's existing code deviates from these rules; follow this document over inconsistent local patterns.  
- **Avoid summaries or outlines** outside this environment. Only provide explanations in chat when contextually required.  
- When uncertain whether to include extended commentary or simplifications, **prefer brevity and adherence to specification** over creative elaboration.  

## Testing Policy
- **Do not** create test files when verifying the function of newly created scripts.
- If a testing file is created for verification purposes, it **must be removed** after testing is complete.

## Function Documentation Policy
- When a new function is added, documentation **must be included** in the `README.md` located in the root project directory.
- **Do not** create separate documentation files for individual functions or utilities.
- The `README.md` should follow markdownlint standards and include clear sections for each function added. Formatting should be consistent with existing documentation style.