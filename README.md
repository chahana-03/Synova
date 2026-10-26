# MoneyTwin: Financial Rehearsal & Decision Simulator

## Team Members
* CHAHANA P P- RRN: 250071601074
* A FAATIMA FAWZIYA- RRN: 250071601274

## Project Description
MoneyTwin is a "try before you spend" financial rehearsal website built for the Code Canvas Hackathon. Instead of acting as a traditional static expense tracker, it features a deterministic daily balance simulation engine, natural-language AI goal parsing via Google Gemini, and a constraint-based reverse budgeting solver ("Find a way, not just a warning") that calculates the earliest safe purchase date while preserving protected buffers and essential expenses.

## AI Tools Used
* Google Gemini API (`gemini-flash-latest` via `google-genai` Python SDK)

## Important Prompts Used
* **Goal Parsing Prompt:**
  ```text
  Extract financial goal parameters from this sentence into JSON format with keys: 
  purchase_amount (number), purchase_day (number), buffer_limit (number).
  Sentence: "{ai_text}"
  Return ONLY valid JSON.
