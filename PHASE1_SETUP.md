# Phase 1 Setup & Testing Guide

## Step 1: Test Locally with Streamlit

### Prerequisites
Make sure you have the dependencies installed:

```bash
pip install -r requirements.txt
```

### Run the App

```bash
streamlit run app.py
```

**What you should see:**
- A browser window opens at `http://localhost:8501`
- The NestAI interface with all 3 sections visible
- When you add apartments, you'll see:
  - **Lifestyle Priority Sliders** at the top
  - **Personalized Rankings** with lifestyle scores
  - **Tradeoff Comparisons** showing gains/losses
  - **Regret Warnings** for potential pain points

### Test the Features

1. **Load Example Listing:**
   - Click "🏢 Load Example Listing"
   - Click "✨ Analyze Apartment"
   - Click "➕ Save Units"

2. **Adjust Lifestyle Priorities:**
   - Move the sliders to different values
   - Watch the rankings change in real-time
   - See how explanations update based on priorities

3. **Explore Tradeoffs:**
   - Expand "💡 Compare to Rank #1/2" sections
   - See what you gain/lose when upgrading apartments

4. **Check Regret Analysis:**
   - Look at the "🚨 Potential Regret Warnings" section
   - Click on apartment sections to see detailed concerns

### Troubleshooting

**Error: "ModuleNotFoundError: No module named 'lifestyle_scoring'"**
- Make sure you're in the NestAI directory
- Run: `pip install -r requirements.txt`

**Error: "FileNotFoundError: data/app_listing_1.txt"**
- The example listing file is missing
- You can paste any Apartments.com text instead

**Sliders not updating rankings:**
- Refresh the page (F5)
- Make sure you have at least 1 saved unit

---

## Step 2: Create a Pull Request (PR)

### Option A: Using GitHub Web Interface (Easiest)

1. Go to your repo: https://github.com/smbrown052/NestAI

2. You should see a banner suggesting "Compare & pull request"
   - Click the green **"Compare & pull request"** button

3. Fill in the PR details:
   ```
   Title:
   ✨ Phase 1: Lifestyle Score, Tradeoff Assistant & Regret Analyzer
   
   Description:
   This PR adds three major Phase 1 features:
   
   ### 🎯 Feature 1: Lifestyle Score
   - Users set 5 lifestyle priorities (Commute, Safety, Nightlife, Budget, Gym)
   - Apartments ranked based on personalized weights
   - Component breakdown shows score for each factor
   
   ### 💡 Feature 2: Tradeoff Assistant
   - Compares ranked apartments and shows gains/losses
   - Example: "If you spend $120 more/month, gain 240 sq ft + in-unit laundry"
   
   ### 🚨 Feature 3: Regret Analyzer
   - Flags potential pain points (long commutes, isolation, missing amenities)
   - Generates "Would I Regret This?" warnings
   - Assigns severity scores (0-100)
   
   ### Files Added
   - lifestyle_scoring.py (150 lines)
   - lifestyle_explanations.py (140 lines)
   - tradeoff_assistant.py (180 lines)
   - regret_analyzer.py (200 lines)
   
   ### Files Modified
   - app.py (integrated all features into UI)
   ```

4. Click **"Create pull request"**

### Option B: Using Command Line (Git)

```bash
# Make sure you're on the feature branch
git checkout feature/lifestyle-score

# Create a PR without leaving terminal
gh pr create --title "✨ Phase 1: Lifestyle Score, Tradeoff Assistant & Regret Analyzer" \
  --body "This PR adds lifestyle-based apartment ranking, tradeoff comparison, and regret analysis features."
```

**Note:** You need GitHub CLI installed: https://cli.github.com/

---

## Step 3: Review & Merge the PR

### Review Your Own Code (Good Practice)

Go to: https://github.com/smbrown052/NestAI/pulls

1. Click on your new PR
2. Click **"Files changed"** tab
3. Review each file:
   - Check for any issues or improvements
   - Comment on specific lines if needed

### Merge the PR

**Option A: Merge via Web (Easiest)**

1. Scroll to bottom of PR
2. Click **"Merge pull request"** (green button)
3. Confirm by clicking **"Confirm merge"**
4. Click **"Delete branch"** (optional, but clean)

**Option B: Merge via Command Line**

```bash
# Switch to main branch
git checkout main

# Pull latest changes
git pull origin main

# Delete local feature branch
git branch -d feature/lifestyle-score
```

---

## Step 4: Update Your Local Main Branch

After merging, get the latest code on your machine:

```bash
# Switch to main
git checkout main

# Pull the merged changes
git pull origin main

# You should now see all Phase 1 features on main
```

### Verify the Merge

```bash
# Check current branch
git branch

# Should show: * main

# View the new files
ls -la lifestyle_*.py
ls -la tradeoff_*.py
ls -la regret_*.py
```

---

## Step 5: Deploy to Streamlit Cloud (Optional)

If you want to share the app publicly:

1. Go to https://share.streamlit.io/
2. Click **"New app"**
3. Select:
   - **Repository:** smbrown052/NestAI
   - **Branch:** main
   - **Main file path:** app.py
4. Click **"Deploy"**

Your app will be live at: `https://share.streamlit.io/smbrown052/NestAI`

---

## Checklist Before Moving to Phase 2

- [ ] Ran `streamlit run app.py` locally and tested all features
- [ ] Created PR and reviewed files changed
- [ ] Merged PR to main branch
- [ ] Pulled main branch to local machine
- [ ] All Phase 1 files are on main branch
- [ ] Ready to start Phase 2 (Google Maps API)

---

## Phase 2 Preview

Once Phase 1 is complete, Phase 2 will add:

1. **Google Maps Commute Intelligence**
   - Show driving, transit, biking times
   - Real-time traffic data
   
2. **Neighborhood Intelligence**
   - Restaurants, gyms, parks nearby
   - Crime rates, walk scores
   
3. **Cost of Living Calculator**
   - Show rent + parking + utilities + fees
   - Total monthly cost breakdown

Estimated time: 2-4 weeks

---

## Questions?

If you get stuck at any step, reference:
- Streamlit docs: https://docs.streamlit.io/
- GitHub PR guide: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
- This repo: https://github.com/smbrown052/NestAI
