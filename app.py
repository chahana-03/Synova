import json
import os
import re
from google import genai
from google.genai import types
import pandas as pd
import streamlit as st

# Page Config
st.set_page_config(
    page_title="MoneyTwin | Financial Rehearsal Simulator", page_icon="⚖️", layout="wide"
)

# Initialize Gemini Client if API key exists
gemini_api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

# --- SESSION STATE FOR LOGIN / USER PROFILE ---
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "user_name" not in st.session_state:
  st.session_state.user_name = ""
if "financial_data" not in st.session_state:
  st.session_state.financial_data = {
      "opening_balance": 5000.0,
      "buffer_limit": 500.0,
      "income_amount": 4000.0,
      "income_day": 10,
      "purchase_amount": 1800.0,
      "purchase_day": 2,
      "daily_spending": 150.0,
  }

# --- LOGIN / SIGNUP SCREEN ---
if not st.session_state.logged_in:
  st.title("⚖️ Welcome to MoneyTwin")
  st.subheader("Preview your money decisions before you spend")

  with st.form("login_form"):
    st.markdown("### Create Your Profile / Login to Start Rehearsing")
    name_input = st.text_input("Your Name / Team Name", value="Student User")

    col1, col2 = st.columns(2)
    with col1:
      init_bal = st.number_input("Current Starting Balance (₹)", value=5000.0)
      buffer_bal = st.number_input("Protected Buffer Limit (₹)", value=500.0)
      income_amt = st.number_input("Next Expected Income (₹)", value=4000.0)
    with col2:
      income_day_val = st.number_input(
          "Expected Income Day (1-30)", value=10, min_value=1, max_value=30
      )
      daily_spend = st.number_input(
          "Estimated Daily Spending (Food/Travel) (₹)", value=150.0
      )

    submitted = st.form_submit_button("Start Financial Rehearsal 🚀")
    if submitted:
      st.session_state.logged_in = True
      st.session_state.user_name = name_input
      st.session_state.financial_data.update({
          "opening_balance": init_bal,
          "buffer_limit": buffer_bal,
          "income_amount": income_amt,
          "income_day": int(income_day_val),
          "daily_spending": daily_spend,
      })
      st.rerun()

  st.stop()

# --- MAIN DASHBOARD (AFTER LOGIN) ---
st.sidebar.markdown(f"👤 **Logged in as:** `{st.session_state.user_name}`")
if st.sidebar.button("Logout / Reset Profile"):
  st.session_state.logged_in = False
  st.rerun()

st.sidebar.divider()
st.sidebar.markdown("### ⚡ Demo & Quick Actions")
if st.sidebar.button("Load Student Demo Example"):
  st.session_state.financial_data = {
      "opening_balance": 5000.0,
      "buffer_limit": 500.0,
      "income_amount": 4000.0,
      "income_day": 10,
      "purchase_amount": 1800.0,
      "purchase_day": 2,
      "daily_spending": 150.0,
  }
  st.rerun()

st.title("💸 MoneyTwin- A Financial Rehearsal ")
st.markdown(
    "*Most of our interface is not about telling you no. It is about finding a"
    " yes that still respects your essentials.*"
)


# --- SIMULATION ENGINE ---
def run_simulation(inputs, overrides=None):
  if overrides is None:
    overrides = {}

  opening = inputs["opening_balance"]
  buffer = inputs["buffer_limit"]
  inc_amt = inputs["income_amount"]
  inc_day = inputs["income_day"] + overrides.get("income_delay", 0)

  daily_spend = inputs["daily_spending"] + overrides.get("travel_increase", 0)

  p_amt = inputs["purchase_amount"]
  p_day = inputs["purchase_day"]

  unexp_amt = overrides.get("unexpected_expense", 0.0)
  unexp_day = overrides.get("unexpected_expense_day", 3)

  timeline = []
  current_bal = opening
  first_buffer_breach = None
  first_zero_breach = None

  for day in range(1, 31):
    day_inc = 0.0
    day_exp = daily_spend
    events = []

    if day == inc_day:
      day_inc = inc_amt
      current_bal += inc_amt
      events.append(f"Income: +₹{inc_amt}")

    if day == unexp_day and unexp_amt > 0:
      day_exp += unexp_amt
      events.append(f"Unexpected: -₹{unexp_amt}")

    if day == p_day and p_amt > 0:
      day_exp += p_amt
      events.append(f"Purchase: -₹{p_amt}")

    current_bal -= day_exp

    if current_bal < buffer and first_buffer_breach is None:
      first_buffer_breach = day
    if current_bal < 0 and first_zero_breach is None:
      first_zero_breach = day

    timeline.append({
        "Day": day,
        "Balance": round(current_bal, 2),
        "Events": ", ".join(events) if events else "Normal",
    })

  return {
      "timeline": timeline,
      "first_buffer_breach": first_buffer_breach,
      "first_zero_breach": first_zero_breach,
      "final_balance": round(current_bal, 2),
  }


# Constraint Solver for Reverse Budgeting
def find_feasible_date(inputs):
  buffer = inputs["buffer_limit"]
  for test_day in range(1, 26):
    test_inputs = inputs.copy()
    test_inputs["purchase_day"] = test_day
    res = run_simulation(test_inputs)
    if res["first_buffer_breach"] is None or res["first_buffer_breach"] > test_day:
      return test_day
  return None


# Layout Inputs
col_left, col_right = st.columns([4, 8])

with col_left:
  st.subheader("🎛️ Scenario Controls")

  # Natural Language AI Goal Input
  ai_text = st.text_area(
      "✨ Natural Language Goal (AI Parser)",
      placeholder="Can I buy a laptop stand for ₹2,500 on Day 2?",
  )
  if st.button("Parse with AI"):
    parsed_successfully = False
    if client and ai_text:
      try:
        prompt = f"""Extract financial goal parameters from this sentence into JSON format with keys: 
                purchase_amount (number), purchase_day (number), buffer_limit (number).
                Sentence: "{ai_text}"
                Return ONLY valid JSON."""
        resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        parsed = json.loads(resp.text)
        if "purchase_amount" in parsed:
          st.session_state.financial_data["purchase_amount"] = float(
              parsed["purchase_amount"]
          )
        if "purchase_day" in parsed:
          st.session_state.financial_data["purchase_day"] = int(
              parsed["purchase_day"]
          )
        st.success("AI parsed goal successfully!")
        parsed_successfully = True
        st.rerun()
      except Exception as e:
        pass  # Fall through to smart local fallback

    if not parsed_successfully and ai_text:
      # Smart Local Fallback Parser
      numbers = re.findall(r"\d+", ai_text.replace(",", ""))
      if numbers:
        amounts = [int(n) for n in numbers if int(n) > 100]
        days = [int(n) for n in numbers if int(n) <= 31]

        if amounts:
          st.session_state.financial_data["purchase_amount"] = float(amounts[0])
        if days:
          st.session_state.financial_data["purchase_day"] = int(days[-1])

        st.success("Locally parsed goal from prompt successfully!")
        st.rerun()
      else:
        st.error("Could not parse goal from text.")

  st.divider()

  # Editable parameters
  st.session_state.financial_data["purchase_amount"] = st.number_input(
      "Purchase Amount (₹)",
      value=st.session_state.financial_data["purchase_amount"],
  )
  st.session_state.financial_data["purchase_day"] = st.number_input(
      "Purchase Day",
      value=st.session_state.financial_data["purchase_day"],
      min_value=1,
      max_value=30,
  )
  st.session_state.financial_data["buffer_limit"] = st.number_input(
      "Protected Buffer (₹)",
      value=st.session_state.financial_data["buffer_limit"],
  )
  st.session_state.financial_data["daily_spending"] = st.number_input(
      "Daily Spending (₹)",
      value=st.session_state.financial_data["daily_spending"],
  )

  st.divider()
  st.markdown("### ⚡ Chaos Stress-Test Scenarios")
  chaos_delay = st.slider("Allowance Delay (Days)", 0, 14, 0)
  chaos_expense = st.number_input("Unexpected Expense (₹)", value=0.0)
  chaos_travel = st.slider("Daily Travel Cost Increase (₹)", 0, 100, 0)

  overrides = {
      "income_delay": chaos_delay,
      "unexpected_expense": chaos_expense,
      "travel_increase": chaos_travel,
  }

with col_right:
  # Run simulations
  current_sim = run_simulation(st.session_state.financial_data, overrides)

  purchase_inputs_no_buy = st.session_state.financial_data.copy()
  purchase_inputs_no_buy["purchase_amount"] = 0
  base_sim = run_simulation(purchase_inputs_no_buy, overrides)

  feasible_day = find_feasible_date(st.session_state.financial_data)

  # Verdict Banner
  if current_sim["first_buffer_breach"]:
    st.error(
        f"⚠️ **Buffer Breach Warning:** Buying on Day"
        f" {st.session_state.financial_data['purchase_day']} drops your balance"
        f" below your ₹{st.session_state.financial_data['buffer_limit']} buffer"
        f" on Day {current_sim['first_buffer_breach']}."
    )
    if feasible_day:
      st.info(
          f"💡 **Reverse Budgeting Suggestion:** Earliest safe purchase date"
          f" preserving your buffer is **Day {feasible_day}**."
      )
  else:
    st.success(
        "✅ **Safe to Proceed:** Your purchase preserves your protected buffer"
        " throughout the month!"
    )

  # Metrics
  m1, m2, m3 = st.columns(3)
  m1.metric(
      "Buffer Status",
      (
          f"Day {current_sim['first_buffer_breach']}"
          if current_sim["first_buffer_breach"]
          else "Safe"
      ),
      delta=(
          "Breached" if current_sim["first_buffer_breach"] else "Protected"
      ),
      delta_color="inverse" if current_sim["first_buffer_breach"] else "normal",
  )
  m2.metric(
      "Zero Risk",
      (
          f"Day {current_sim['first_zero_breach']}"
          if current_sim["first_zero_breach"]
          else "None"
      ),
  )
  m3.metric("Month-End Balance", f"₹{current_sim['final_balance']}")

  st.subheader("📈 Projected Balance Timelines")
  df_chart = pd.DataFrame({
      "Day": [d["Day"] for d in base_sim["timeline"]],
      "Current Plan (No Purchase)": [d["Balance"] for d in base_sim["timeline"]],
      "With Purchase Decision": [d["Balance"] for d in current_sim["timeline"]],
  }).set_index("Day")

  st.line_chart(df_chart)

  with st.expander("🔍 View Detailed Daily Ledger & Events"):
    df_details = pd.DataFrame(current_sim["timeline"])
    st.dataframe(df_details, use_container_width=True)