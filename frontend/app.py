import time
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Trip Planner",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-title { font-size: 2.8rem; font-weight: 800; color: #1a3c5e; text-align: center; }
    .sub-title  { font-size: 1.1rem; color: #555; text-align: center; margin-bottom: 2rem; }
    .card       { background: #f0f6ff; border-radius: 12px; padding: 1.2rem; margin-bottom: 1rem; border-left: 4px solid #2e6da4; }
    .day-card   { background: #fff; border-radius: 10px; padding: 1rem; margin-bottom: 0.8rem;
                  box-shadow: 0 2px 6px rgba(0,0,0,0.08); border-top: 3px solid #2e6da4; }
    .budget-ok  { color: #1a7a4a; font-weight: 700; }
    .budget-over{ color: #c0392b; font-weight: 700; }
    .tag        { display: inline-block; background: #e8f0fe; color: #1a3c5e; border-radius: 20px;
                  padding: 2px 12px; font-size: 0.82rem; margin: 2px; }
    .section-header { font-size: 1.3rem; font-weight: 700; color: #1a3c5e;
                      border-bottom: 2px solid #2e6da4; padding-bottom: 4px; margin: 1.2rem 0 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">✈️ AI Trip Planner</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Powered by LangGraph · Multi-Agent AI · GPT-4o-mini</div>', unsafe_allow_html=True)
st.divider()


# ── Sidebar — Input form ──────────────────────────────────────────────────────
with st.sidebar:
    st.header("🗺️ Plan Your Trip")
    st.caption("Fill in the details below and hit **Plan My Trip**.")

    user_id = st.text_input("Your Name / User ID", value="traveler_01", help="Used to remember your preferences across trips.")

    st.subheader("Route")
    col1, col2 = st.columns(2)
    with col1:
        origin = st.text_input("From", placeholder="Bangalore")
    with col2:
        destination = st.text_input("To", placeholder="Goa")

    st.subheader("Dates & People")
    col3, col4 = st.columns(2)
    with col3:
        start_date = st.date_input("Departure")
    with col4:
        end_date = st.date_input("Return")

    travelers = st.number_input("Travelers", min_value=1, max_value=20, value=2)

    st.subheader("Budget")
    currency = st.selectbox("Currency", ["INR ₹", "USD $", "EUR €"])
    budget_amount = st.number_input("Total Budget", min_value=1000, value=30000, step=1000)
    currency_map = {"INR ₹": "INR", "USD $": "USD", "EUR €": "EUR"}
    currency_code = currency_map[currency]

    st.subheader("Preferences")
    trip_type = st.selectbox("Trip Type", ["Beach", "Leisure", "Adventure", "Honeymoon", "Family", "Business"])
    budget_style = st.selectbox("Stay Style", ["Budget", "Mid-range", "Luxury"])
    dietary = st.multiselect("Dietary Preferences", ["Vegetarian", "Vegan", "Halal", "Seafood", "No restrictions"], default=["No restrictions"])
    activities = st.multiselect("Interests", ["Sightseeing", "Nightlife", "Trekking", "Shopping", "Food tours", "Beaches", "Culture & History"], default=["Sightseeing"])
    transport_pref = st.selectbox("Preferred Transport", ["Flight", "Train", "Bus", "Any"])

    extra_notes = st.text_area("Any special requests?", placeholder="e.g. Need accessible rooms, celebrating anniversary...")

    st.divider()
    submit = st.button("🚀 Plan My Trip", use_container_width=True, type="primary")


# ── Build natural language prompt ─────────────────────────────────────────────
def build_prompt() -> str:
    dietary_str = ", ".join(d for d in dietary if d != "No restrictions") or "no restrictions"
    acts_str = ", ".join(activities) or "general sightseeing"
    days = (end_date - start_date).days
    return (
        f"Plan a {days}-day trip from {origin} to {destination} "
        f"for {travelers} {'person' if travelers == 1 else 'people'} "
        f"({trip_type.lower()} trip). "
        f"Travel dates: {start_date} to {end_date}. "
        f"Total budget: {budget_amount} {currency_code}. "
        f"Stay preference: {budget_style.lower()}. "
        f"Dietary: {dietary_str}. "
        f"Interests: {acts_str}. "
        f"Preferred transport: {transport_pref.lower()}. "
        + (f"Special requests: {extra_notes}." if extra_notes else "")
    )


# ── Helper: poll status until done ───────────────────────────────────────────
def poll_status(session_id: str, status_box, progress_bar) -> dict | None:
    phases = {
        "starting":             (5,  "🔍 Understanding your trip..."),
        "user_input_agent":     (10, "📋 Processing trip details..."),
        "memory_agent":         (18, "🧠 Checking your travel history..."),
        "weather_agent":        (30, "🌤️ Fetching weather forecast..."),
        "transport_agent":      (42, "✈️ Searching flights & transport..."),
        "hotel_agent":          (54, "🏨 Finding best hotels..."),
        "places_agent":         (63, "📍 Discovering places to visit..."),
        "budget_agent":         (72, "💰 Optimizing your budget..."),
        "itinerary_agent":      (83, "📅 Building your day-wise itinerary..."),
        "final_review_agent":   (92, "✅ Reviewing the complete plan..."),
        "pdf_generator_agent":  (98, "📄 Generating your PDF report..."),
        "done":                 (100,"🎉 Your trip plan is ready!"),
    }

    for _ in range(150):  # max 150 × 2s = 5 min
        try:
            resp = requests.get(f"{API_BASE}/trips/{session_id}/status", timeout=5)
            data = resp.json()
        except Exception:
            time.sleep(2)
            continue

        status = data.get("status", "")
        phase  = data.get("current_phase", "starting") or "starting"

        pct, msg = phases.get(phase, (50, f"⚙️ Working... ({phase})"))
        progress_bar.progress(pct / 100)
        status_box.info(msg)

        if status in ("completed", "partial", "failed"):
            return data

        time.sleep(2)

    return None


# ── Render helpers ────────────────────────────────────────────────────────────
def render_budget(budget: dict):
    st.markdown('<div class="section-header">💰 Budget Breakdown</div>', unsafe_allow_html=True)
    total = budget.get("total_budget", 0)
    spent = budget.get("total_spent", 0)
    remaining = budget.get("remaining", 0)
    within = budget.get("within_budget", True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Budget", f"${total:,.0f}")
    col2.metric("Estimated Spend", f"${spent:,.0f}", delta=f"{'over' if not within else 'under'} by ${abs(remaining):,.0f}", delta_color="inverse" if not within else "normal")
    col3.metric("Remaining", f"${remaining:,.0f}")

    st.markdown("""
| Category | Cost |
|---|---|
| ✈️ Transport | ${transport_cost:,.0f} |
| 🏨 Hotel | ${hotel_cost:,.0f} |
| 🎭 Activities | ${activities_cost:,.0f} |
| 🍽️ Food | ${food_cost:,.0f} |
| 🎒 Miscellaneous | ${misc_cost:,.0f} |
""".format(**budget))

    tips = budget.get("optimizations", [])
    if tips:
        with st.expander("💡 Cost-saving tips"):
            for tip in tips:
                st.markdown(f"• {tip}")


def render_itinerary(itinerary: dict):
    st.markdown('<div class="section-header">📅 Day-wise Itinerary</div>', unsafe_allow_html=True)
    days = itinerary.get("days", [])
    if not days:
        st.warning("Itinerary not available.")
        return

    for day in days:
        with st.expander(f"**Day {day.get('day')} — {day.get('date', '')}**", expanded=(day.get('day') == 1)):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.markdown("**🌅 Morning**")
                for item in day.get("morning", []):
                    st.markdown(f"• {item}")
            with col_b:
                st.markdown("**☀️ Afternoon**")
                for item in day.get("afternoon", []):
                    st.markdown(f"• {item}")
            with col_c:
                st.markdown("**🌙 Evening**")
                for item in day.get("evening", []):
                    st.markdown(f"• {item}")

            meals = day.get("meals", [])
            if meals:
                st.markdown("**🍽️ Meals:** " + " · ".join(meals))

            hotel = day.get("hotel", "")
            if hotel:
                st.markdown(f"**🏨 Stay:** {hotel}")

            transport_note = day.get("transport_notes", "")
            if transport_note:
                st.markdown(f"**🚗 Transport:** {transport_note}")

    conflicts = itinerary.get("conflicts", [])
    if conflicts:
        st.warning("**Notes from the planner:**")
        for c in conflicts:
            st.markdown(f"⚠️ {c}")


def render_transport(transport: dict):
    st.markdown('<div class="section-header">✈️ Transport</div>', unsafe_allow_html=True)
    rec = transport.get("recommended", {})
    if rec:
        cols = st.columns(4)
        cols[0].metric("Mode", rec.get("mode", "—").title())
        cols[1].metric("Operator", rec.get("operator", "—"))
        cols[2].metric("Duration", rec.get("duration", "—"))
        cols[3].metric("Est. Cost", f"${transport.get('estimated_cost_usd', 0):,.0f}")
    notes = transport.get("notes", "")
    if notes:
        st.caption(notes)


def render_hotel(hotel: dict):
    st.markdown('<div class="section-header">🏨 Hotel</div>', unsafe_allow_html=True)
    rec = hotel.get("recommended", {})
    if rec:
        cols = st.columns(4)
        cols[0].metric("Hotel", rec.get("name", "—"))
        cols[1].metric("Stars", "⭐" * int(rec.get("stars", 3)))
        cols[2].metric("Rating", f"{rec.get('rating', 0)} / 5")
        cols[3].metric("Est. Stay Cost", f"${hotel.get('estimated_cost_usd', 0):,.0f}")


def render_review(review: dict):
    approved = review.get("approved", True)
    if approved:
        st.success("✅ Plan reviewed and approved by AI reviewer.")
    else:
        st.warning("⚠️ Plan approved with notes — see conflicts below.")

    for conflict in review.get("conflicts", []):
        st.error(f"• {conflict}")
    for warning in review.get("warnings", []):
        st.warning(f"• {warning}")


# ── Main area — results ───────────────────────────────────────────────────────
if submit:
    if not origin or not destination:
        st.error("Please enter both origin and destination.")
        st.stop()
    if start_date >= end_date:
        st.error("Return date must be after departure date.")
        st.stop()

    prompt = build_prompt()

    st.subheader("🤖 Planning your trip...")
    st.caption(f"**Request:** {prompt}")

    status_box   = st.empty()
    progress_bar = st.progress(0)

    # Submit to API
    try:
        resp = requests.post(
            f"{API_BASE}/trips",
            json={"user_id": user_id, "raw_input": prompt},
            timeout=10,
        )
        resp.raise_for_status()
        session_id = resp.json()["session_id"]
        st.session_state["session_id"] = session_id
        status_box.info("✅ Request accepted! Agents are now working...")
    except Exception as e:
        st.error(f"Could not reach the API server. Make sure it's running on port 8000.\n\nError: {e}")
        st.stop()

    # Poll until done
    final = poll_status(session_id, status_box, progress_bar)

    if not final:
        st.error("Timed out waiting for the plan. Please try again.")
        st.stop()

    if final.get("status") == "failed":
        st.error("Trip planning failed. Errors: " + str(final.get("errors", [])))
        st.stop()

    progress_bar.progress(1.0)
    status_box.success("🎉 Your trip plan is ready!")

    st.balloons()
    st.divider()

    # ── PDF download button (top) ──
    pdf_url = final.get("pdf_download_url")
    if pdf_url:
        pdf_bytes = requests.get(f"{API_BASE}{pdf_url}").content
        st.download_button(
            label="📥 Download Full Trip Report (PDF)",
            data=pdf_bytes,
            file_name=f"trip_{destination.replace(' ', '_')}.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )
        st.divider()

    # ── Trip results ──
    tab1, tab2, tab3, tab4 = st.tabs(["📅 Itinerary", "💰 Budget", "✈️ Transport & Hotel", "✅ Review"])

    with tab1:
        itinerary = final.get("itinerary") or {}
        render_itinerary(itinerary)

    with tab2:
        budget = final.get("budget_summary") or {}
        render_budget(budget)

    with tab3:
        prefs = final.get("trip_preferences") or {}
        transport = (final.get("budget_summary") or {})  # fallback
        st.markdown(f"**Destination:** {prefs.get('destination', destination)}")
        st.markdown(f"**Dates:** {prefs.get('start_date', str(start_date))} → {prefs.get('end_date', str(end_date))}")
        st.markdown(f"**Travelers:** {prefs.get('travelers', travelers)}")

    with tab4:
        review = final.get("review_status") or {}
        render_review(review)

elif "session_id" not in st.session_state:
    # Landing state — show instructions
    st.markdown("""
    <div style="text-align:center; padding: 3rem 2rem; color: #888;">
        <div style="font-size: 4rem;">🗺️</div>
        <h3 style="color: #444;">Fill in your trip details on the left and click <b>Plan My Trip</b></h3>
        <p>The AI will coordinate multiple agents to build your complete travel plan including<br>
        flights, hotels, day-wise itinerary, budget breakdown, and a downloadable PDF report.</p>
    </div>
    """, unsafe_allow_html=True)

    st.info("⚙️ Make sure the backend API server is running: `python -m uvicorn api.main:app --reload --port 8000`")

    with st.expander("How it works"):
        st.markdown("""
        1. **User Input Agent** — Extracts and normalizes your trip requirements
        2. **Memory Agent** — Recalls your past trip preferences
        3. **Weather Agent** — Fetches destination weather forecast *(runs in parallel)*
        4. **Transport Agent** — Searches flights and routes *(runs in parallel)*
        5. **Hotel Agent** — Finds hotels within your budget *(runs in parallel)*
        6. **Places Agent** — Discovers attractions and restaurants *(runs in parallel)*
        7. **Budget Agent** — Calculates costs and suggests savings
        8. **Itinerary Agent** — Creates a detailed day-wise plan
        9. **Final Review Agent** — Validates the plan for conflicts
        10. **PDF Generator Agent** — Produces your downloadable report
        """)
