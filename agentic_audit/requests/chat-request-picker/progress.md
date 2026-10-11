# Progress

Committed prior session logging work as 07b9330. Added provider-free request option discovery and audited request selection. Choices include the latest coding run and its status; selecting an existing run preserves normal workflow checks and never transfers plan approval. Request-only commands still resolve a sole bundle automatically. Commands requiring a run offer selection when no run is selected.

Terminal picker committed as ee23ac7 with a scrollable request list, Up/Down, Enter, and Escape. Cancel preserves the command. Selection resumes commands on the latest coding run; unprepared requests offer /prepare. /approve after selection opens review and requires another explicit approval. Real pipe-input keyboard tests cover navigation, cancellation, resuming /plan, ambiguous /prepare, and unprepared/empty projects. All 13 terminal tests pass.
