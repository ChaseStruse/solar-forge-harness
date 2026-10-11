# Implementation plan

1. Resolve the target: shared Forge personality or an Ollama-specific Modelfile.
2. Use the drafted voice as a reusable instruction resource: warm, useful, candid,
   with dry wit and occasional affectionate teasing. Match context and stop joking
   when asked. Preserve structured output and execution/approval boundaries.
3. Integrate through the selected model instruction path and document how it works.
4. Run the required regression suite; verify the instruction reaches provider calls
   and is recorded in audits. No scripted response can prove a live model's humor;
   distinguish wiring verification from qualitative model evaluation.
5. Commit the implementation and evidence in small stages.
