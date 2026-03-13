# Apartment Compare AI

**Live App:** (https://apartment-comparison-and-recommendation.streamlit.app/)

User Instructions:
- You can paste text copied from apartments.com (web scraping is not acceptable per apartment.com terms so it must be pasted manually into the app)
- I have pre-loaded 2 sample texts that you can click on
- Then, 'Extract Text' to see the unstructured data become structured
- Click 'Add to comparison table'
- Repeat for the second sample text
- Once both are in the comparison table, you can adjust filters
- There is an LLM powered search tool that will give you the top 3 units based on your specifications, and explain why they are ordered as such

AI-powered tool that converts unstructured apartment listing text into structured data and ranks units based on user preferences.

The application helps renters quickly evaluate multiple apartments by extracting pricing, square footage, availability, amenities, and walkability information from copied listing pages and presenting them in a searchable comparison interface.

---

# Product Vision

Apartment search platforms often make it difficult to compare multiple listings because information is spread across different pages and presented inconsistently.

The goal of Apartment Compare AI is to create a lightweight decision-support tool that:

- Converts messy listing text into structured datasets
- Enables side-by-side unit comparison
- Uses AI to match listings with user preferences
- Surfaces the best value units automatically

The product acts as a **personal apartment analysis assistant** for renters evaluating multiple options.

---

# Target Users

Primary users include:

### Urban renters
Evaluating multiple apartment buildings simultaneously.

### Relocating professionals
Comparing listings quickly without manually copying data.

### Students or interns
Trying to maximize value while staying within a budget.

---

# Product Requirements

## Listing Parsing

The system must accept pasted apartment listing text and extract:

- property title
- floorplan information
- unit number
- rent price
- square footage
- availability date
- amenities
- apartment features
- walkability metrics (Walk Score, Transit Score, Bike Score)

---

## Data Structuring

The system converts unstructured listing text into structured rows and calculates additional metrics including:

- rent per square foot
- best deal score
- floor level derived from unit number

---

## Comparison Engine

Users can compare units across listings using:

- price
- size
- availability
- walkability
- building amenities

---

## Filtering & Sorting

Users can filter results by:

- budget
- minimum square footage
- availability window
- floor level

Users can sort results by:

- best deal score
- lowest price
- largest unit
- price per square foot
- soonest availability
- highest floor
- walk score

---

## AI Matching

Users can describe what they want in natural language.

Example:

"I want the best value one-bedroom under $2500 with as much space as possible and available soon."

The system:

1. Converts the prompt into structured preferences using an LLM  
2. Ranks all units against those preferences  
3. Returns the best matches with an explanation  

---

# Design Intent

This project intentionally focuses on three core product design principles.

---

## Reduce Cognitive Load

Apartment listing pages contain large amounts of information that are difficult to compare.

This product simplifies the decision process by:

- structuring data into a table
- computing value metrics automatically
- ranking the best units

Users should be able to identify strong options within seconds.

---

## Augment Decision Making With AI

Instead of manually filtering dozens of listings, users can describe preferences in natural language.

AI converts qualitative user intent into structured filters and scoring logic.

This creates a more intuitive search experience.

---

## Extract Value From Unstructured Data

Most apartment websites do not expose structured listing data for easy comparison.

The parser transforms messy listing text into structured datasets enabling:

- filtering
- ranking
- scoring
- analysis

This demonstrates how lightweight parsing + AI can unlock value from semi-structured web content.

---

# System Architecture
User Interface (Streamlit)
│
▼
Listing Parser
(parser/apartment_listing.py)
│
▼
Structured Dataset
(Pandas DataFrame)
│
├── Value Calculations
│ rent per sqft
│ deal score
│ floor level
│
▼
AI Preference Engine
(llm_helpers.py)
│
▼
AI Ranking Engine
(ranking.py)
│
▼
Interactive Comparison UI

---

# Key Product Features

## Automated Unit Extraction

The parser identifies unit blocks such as:
Unit 1631
price $2,656
square feet 724
availability Now

and converts them into structured records.

---

## Derived Value Metrics

The system calculates signals useful for apartment evaluation:

- rent per square foot
- best deal score
- floor level
- availability timing

---

## Natural Language Apartment Search

Users can describe preferences in plain English.

Example:

and converts them into structured records.

---

## Derived Value Metrics

The system calculates signals useful for apartment evaluation:

- rent per square foot
- best deal score
- floor level
- availability timing

---

## Natural Language Apartment Search

Users can describe preferences in plain English.

Example:

The system translates this into structured ranking criteria.

---

## Intelligent Ranking

Listings are scored based on:

- price efficiency
- size
- availability
- walkability
- AI preference matching

---

# Example Use Case

A renter evaluating several buildings can:

1. Copy listing pages from apartment websites  
2. Paste the content into the tool  
3. Automatically extract unit data  
4. Filter by budget and size  
5. Ask AI to recommend the best units  

The tool produces a ranked shortlist with explanations.

---

# Technology Stack

- Python
- Streamlit
- Pandas
- Regex-based parsers
- OpenAI API (LLM preference parsing & explanations)

---

# Future Enhancements

Potential roadmap improvements include:

- multi-floorplan parsing
- direct listing URL ingestion
- commute-time analysis
- neighborhood scoring
- historical rent trend tracking
- interactive map visualization

---

# Why This Project Matters

This project demonstrates the ability to:

- identify a real user pain point
- design a product around it
- translate product requirements into working software
- integrate AI into a user-facing decision workflow

It showcases both **technical execution and product thinking**, which are critical for product management roles in AI-driven products.
