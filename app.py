import os
import streamlit as st
import pandas as pd
from text_parser import parse_apartment_text, filter_units_by_request

st.title("Nest AI")

st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}
.hero {
    background: linear-gradient(135deg, #fffaf4 0%, #e9f1e6 100%);
    padding: 2rem;
    border-radius: 24px;
    border: 1px solid #e3ddd4;
    margin-bottom: 1rem;
    box-shadow: 0 8px 24px rgba(80, 70, 60, 0.08);
}
.hero h1 {
    font-size: 3.2rem;
    margin-bottom: 0.25rem;
    color: #2f3a2f;
}
.hero p {
    font-size: 1.1rem;
    color: #6c6258;
}
.section-card {
    background-color: white;
    padding: 1.5rem;
    border-radius: 20px;
    border: 1px solid #e7e0d8;
    margin-top: 1rem;
    box-shadow: 0 4px 14px rgba(80, 70, 60, 0.05);
}
.stButton > button {
    background-color: #50624f;
    color: white;
    border-radius: 999px;
    border: none;
    padding: 0.65rem 1.4rem;
    font-weight: 600;
}
.stButton > button:hover {
    background-color: #39483a;
    color: white;
}
.small-muted {
    color: #7a7168;
    font-size: 0.95rem;
}
</style>
""", unsafe_allow_html=True)
st.set_page_config(page_title="NestAI", layout="wide")

st.title("NestAI")
st.markdown("### Find *your* nest.")


def format_travel(mode, minutes):
    if mode and minutes:
        return f"{mode.title()} · {minutes} min"
    return "—"


AVALON_EXAMPLE = """
Map
 English
Apartments.com Logo
Manage Rentals     
Sign Up
/
Sign In
Prevto previous listing
Nextto next listing

 
 
39 Photos
2 Virtual Tours
Contact This Property
Tour Options: Self-Guided 


(301) 778-2961

 Language: English

 Open 9am - 7pm Today

View All Hours

Virginia  Arlington County  Arlington  Clarendon/Courthouse 
Avalon Courthouse Place
1320 N Veitch St, Arlington, VA 22201
2.5
Renter Rating
13 Reviews
Verified Listing
Today



Property Management Company Logo
Total Monthly Price

$2,321 - $4,061

Bedrooms

1 - 2 bd

Bathrooms

1 - 2 ba

Square Feet

525 - 1,265 sq ft

Move-in Special

* Apply by 6/18 for 1 month off! * Terms and conditions apply.

Highlights
Walker's Paradise
Furnished Units Available
Pool
Walk-In Closets
Patio
Business Center
Pricing & Floor Plans
filter results by bedrooms
All
1 Bedroom
2 Bedrooms
Cost Calculator: Estimate your monthly and one-time fees. 
650
$2,459 – $2,460
Total Monthly Price
1 Bed
1 Bath
650 Sq Ft
$300 Deposit
View 650Floor Plan Details
Tour Floor Plan
2 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0535
price
$2,459
square feet
650
availibilityJun 15
Unit
1235
price
$2,460
square feet
650
availibilityJun 28
724-b
$2,576 – $2,616
Total Monthly Price
1 Bed
1 Bath
724 Sq Ft
$300 Deposit
View 724-bFloor Plan Details
Tour Floor Plan
6 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1110
price
$2,606
square feet
724
availibilityJun 15
Unit
1009
price
$2,586
square feet
724
availibilityJun 28
Unit
1208
price
$2,596
square feet
724
availibilityJul 31
Show More Units (3)

665
$2,571 – $2,841
Total Monthly Price
1 Bed
1 Bath
665 Sq Ft
$300 Deposit
View 665Floor Plan Details
Tour Floor Plan
4 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1720
price
$2,571
square feet
665
availibilityJun 15
Unit
0520
price
$2,590
square feet
665
availibilityJun 15
Unit
0620
price
$2,631
square feet
665
availibilityJul 8
Show More Units (1)

740-a
$2,577 – $2,672
Total Monthly Price
1 Bed
1 Bath
740 Sq Ft
$300 Deposit
View 740-aFloor Plan Details
Tour Floor Plan
4 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1506
price
$2,577
square feet
740
availibilityJun 15
Unit
2006
price
$2,614
square feet
740
availibilityJun 15
Unit
1634
price
$2,672
square feet
740
availibilityJul 7
Show More Units (1)

724-a
$2,606 – $2,686
Total Monthly Price
1 Bed
1 Bath
724 Sq Ft
$300 Deposit
View 724-aFloor Plan Details
Tour Floor Plan
2 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1104
price
$2,606
square feet
724
availibilityJun 15
Unit
1406
price
$2,686
square feet
724
availibilityJun 15
755
$2,612 – $2,757
Total Monthly Price
1 Bed
1 Bath
755 Sq Ft
$300 Deposit
View 755Floor Plan Details
Tour Floor Plan
4 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0927
price
$2,612
square feet
755
availibilityJun 15
Unit
1913
price
$2,694
square feet
755
availibilityJun 16
Unit
1127
price
$2,642
square feet
755
availibilityJun 27
Show More Units (1)

745
$2,651
Total Monthly Price
1 Bed
1 Bath
745 Sq Ft
$300 Deposit
View 745Floor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1622
price
$2,651
square feet
745
availibilityJun 15
740sf-b
$2,714 – $2,767
Total Monthly Price
1 Bed
1 Bath
740 Sq Ft
$300 Deposit
View 740sf-bFloor Plan Details
Tour Floor Plan
2 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1808
price
$2,767
square feet
740
availibilityJun 15
Unit
2032
price
$2,714
square feet
740
availibilityAug 21
800
$2,766
Total Monthly Price
1 Bed
1 Bath
800 Sq Ft
$300 Deposit
View 800Floor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1433
price
$2,766
square feet
800
availibilityJun 15
615
$2,416 – $2,431
Total Monthly Price
1 Bed
1 Bath
615 Sq Ft
$300 Deposit
View 615Floor Plan Details
Tour Floor Plan
2 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1518
price
$2,431
square feet
615
availibilityJul 17
Unit
0318
price
$2,416
square feet
615
availibilityJul 28
870-a
$2,888
Total Monthly Price
1 Bed
1 Bath
870 Sq Ft
$300 Deposit
View 870-aFloor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0438
price
$2,888
square feet
870
availibilityJul 25
525
$2,321
Total Monthly Price
1 Bed
1 Bath
525 Sq Ft
$300 Deposit
View 525Floor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0405
price
$2,321
square feet
525
availibilityJul 27
730
$2,621
Total Monthly Price
1 Bed
1 Bath
730 Sq Ft
$300 Deposit
View 730Floor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0328
price
$2,621
square feet
730
availibilityAug 19
855
$2,905 – $2,956
Total Monthly Price
1 Bed
1 Bath
855 Sq Ft
$300 Deposit
View 855Floor Plan Details
Tour Floor Plan
3 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0916
price
$2,953
square feet
855
availibilityAug 21
Unit
1624
price
$2,956
square feet
855
availibilityAug 21
Unit
0524
price
$2,905
square feet
855
availibilityAug 22
870-b
$2,882
Total Monthly Price
1 Bed
1 Bath
870 Sq Ft
$300 Deposit
View 870-bFloor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0503
price
$2,882
square feet
870
availibilityAug 25
1075
$3,690 – $3,782
Total Monthly Price
2 Beds
2 Baths
1,075 Sq Ft
$300 Deposit
View 1075Floor Plan Details
Tour Floor Plan
2 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1503
price
$3,690
square feet
1,075
availibilityJun 15
Unit
1437
price
$3,782
square feet
1,075
availibilityJul 17
1125
$3,945
Total Monthly Price
2 Beds
2 Baths
1,125 Sq Ft
$300 Deposit
View 1125Floor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1438
price
$3,945
square feet
1,125
availibilityJun 15
1070
$3,772 – $3,922
Total Monthly Price
2 Beds
2 Baths
1,070 Sq Ft
$300 Deposit
View 1070Floor Plan Details
Tour Floor Plan
3 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1101
price
$3,772
square feet
1,070
availibilityJun 23
Unit
1001
price
$3,890
square feet
1,070
availibilityJul 15
Unit
1201
price
$3,922
square feet
1,070
availibilityAug 20
1030
$3,679 – $3,883
Total Monthly Price
2 Beds
2 Baths
1,030 Sq Ft
$300 Deposit
View 1030Floor Plan Details
Tour Floor Plan
5 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0528
price
$3,808
square feet
1,030
availibilityJul 2
Unit
1612
price
$3,727
square feet
1,030
availibilityJul 14
Unit
1228
price
$3,883
square feet
1,030
availibilityJul 30
Show More Units (2)

1060
$3,911
Total Monthly Price
2 Beds
2 Baths
1,060 Sq Ft
$300 Deposit
View 1060Floor Plan Details
Tour Floor Plan
1 Available unit
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
1926
price
$3,911
square feet
1,060
availibilityJul 11
1265
$3,811 – $4,061
Total Monthly Price
2 Beds
2 Baths
1,265 Sq Ft
$300 Deposit
View 1265Floor Plan Details
Tour Floor Plan
4 Available units
Unit
Total Price
Sq Ft
Availability
Unit Details
Unit
0921
price
$4,061
square feet
1,265
availibilityJul 24
Unit
0721
price
$3,811
square feet
1,265
availibilityJul 29
Unit
0621
price
$4,036
square feet
1,265
availibilityJul 30
Show More Units (1)

* Price shown is total price based on community-supplied monthly required fees. Excludes user-selected optional fees and variable or usage-based fees and required charges due at or prior to move-in or at move-out.View Fees and Policies for details. Price, availability, fees, and any applicable rent special are subject to change without notice.
* Square footage definitions vary. Displayed square footage is approximate.
Fees and Policies
The fees listed below are community-provided and may exclude utilities or add-ons. All payments are made directly to the property and are non-refundable unless otherwise specified. Use the Cost Calculator to determine costs based on your needs.

Required Fees Pets Parking Storage
Utilities & Essentials
Technology Connect
$81 / mo
One-Time Basics
Due at Application
Application Fees
$50
Due at Move-In
Security Deposit
$300
Common Area/Amenities
$500
Property Fee Disclaimer: Based on community-supplied data and independent market research. Subject to change without notice. May exclude fees for mandatory or optional services and usage-based utilities.

Details
Utilities Included
Trash Removal
Lease Options
2 - 12 Month Leases
Short term lease
Property Information
Built in 1999
564 units/20 stories
Furnished Units Available
Matterport 3D Tours
Interior

1BR Vacant
1/2

About Avalon Courthouse Place
Avalon Courthouse Place, a short walk to the Courthouse Metro, offers spacious furnished and unfurnished one and two bedroom Arlington apartments with excellent amenities like private patios, large walk-in closets, plush wall-to-wall carpeting, separate dining rooms and deluxe kitchens. Our Furnished+ homes come outfitted with essential stylish furniture plus all utilities, including cable and WiFi, are included in your rent. Superb community facilities include a split-level pool, a high-tech business center, a library, the sports club and much more. The combination of amazing features and a professional on-site staff makes Avalon Courthouse Place the ideal choice.

Avalon Courthouse Place is an apartment community located in Arlington County and the 22201 ZIP Code. This area is served by the Arlington County Public Schools attendance zone.

Unique Features

$500 Amenity Fee
Tech Package W/ High-speed Wifi And More
Contact
(301) 778-2961
View Property Website
Language: English
Open 9am - 7pm Today
View All HoursView All Hours
Property Management Company Logo
Community Amenities
Furnished Units Available
Business Center
Pool
Apartment Features
Washer/Dryer

Air Conditioning

Walk-In Closets

Microwave

Wi-Fi
Washer/Dryer
Air Conditioning
Cable Ready
Disposal
Kitchen
Microwave
Dining Room
Walk-In Closets
Furnished
Patio
Location
1320 N Veitch St, Arlington, VA 22201
 Get Directions
Schools
Restaurants
Groceries
Coffee
Banks
Shops
Fitness
Add a Commute
Neighborhood

In many ways, Arlington’s Clarendon/Courthouse neighborhood leads a double life. On the one hand, the mix of upscale single-family homes and swanky apartments combined with the super-convenient access to Washington (just a mile away and served by multiple Metro stops) make this an ideal location for DC-area commuters seeking a more suburban home environment. The abundance of parks and playgrounds reflects the family-friendly nature of the community, and the local public schools are among the best in the region. Parts of the neighborhood also contain several corporate high-rises, giving many folks the option of walking to work.

However, Clarendon/Courthouse also has a lively, fun side. The neighborhood is generally known as the nightlife capital of Arlington – the robust bar and club scene along Clarendon Avenue attracts partiers from across the DC area on weekends.

Learn more about living in Clarendon/Courthouse  
Average Prices by Area
Compare neighborhood and city base rent averages by bedroom.

Clarendon/Courthouse	Arlington, VA
Studio	$2,333	$2,027
1 Bedroom	$2,593	$2,377
2 Bedrooms	$3,749	$3,149
3 Bedrooms	$4,579	$4,145
Education
Colleges & Universities			Distance
George Mason Univ., Arlington
Drive:	4 min	1.2 mi
Georgetown University
Drive:	7 min	2.8 mi
GWU, Foggy Bottom
Drive:	6 min	3.1 mi
GWU, Mount Vernon
Drive:	8 min	3.7 mi
Avalon Courthouse Place is within 4 minutes or 1.2 miles from George Mason Univ., Arlington. It is also near Georgetown University and GWU, Foggy Bottom.
Schools
Public Schools Private Schools
Escuela Key Elementary
Public Elementary School
Grades PK-5
618 Students
 Nearby

Arlington Science Focus School
Public Elementary School
Grades PK-5
549 Students
 Attendance Zone

Jefferson Middle
Public Middle School
Grades 6-8
1,053 Students
 Nearby

Dorothy Hamm Middle
Public Middle School
Grades 6-8
899 Students
 Attendance Zone

Yorktown High School
Public High School
Grades 9-12
2,577 Students
 Attendance Zone

School data provided by  
Transportation
Transportation options available in Arlington include Court House, Orange,Silver Line Center Platform, located 0.2 mile from Avalon Courthouse Place. Avalon Courthouse Place is near Ronald Reagan Washington Ntl, located 5.8 miles or 11 minutes away, and Washington Dulles International, located 24.4 miles or 40 minutes away.

Transit / Subway			Distance
Court House, Orange,Silver Line Center Platform	Walk:	3 min	0.2 mi
Clarendon  	Walk:	12 min	0.6 mi
Virginia Square-Gmu  	Drive:	4 min	1.5 mi
Rosslyn   	Drive:	3 min	1.6 mi
Arlington Cemetery 	Drive:	4 min	2.1 mi
 
Commuter Rail			Distance
4	Drive:	8 min	4.2 mi
Lead	Drive:	10 min	5.3 mi
Union Station      	Drive:	11 min	5.5 mi
1	Drive:	16 min	6.7 mi
Alexandria	Drive:	16 min	6.8 mi
 
Airports			Distance
Ronald Reagan Washington Ntl	Drive:	11 min	5.8 mi
Washington Dulles International	Drive:	40 min	24.4 mi
Getting Around
Exceptionally Walkable
Walkability
90
/ 100
Good Public Transit
Transit
70
/ 100
Fairly Drivable
Drivability
50
/ 100
Moderately Bikeable
Bikeability
70
/ 100
Scores provided by


Active
Soundscore™
69
/ 100
Traffic

Active
Airport

Calm
Businesses

Busy
Scores provided by

HowLoud
Points of Interest
Time and distance from Avalon Courthouse Place.

Shopping Centers			Distance
The Crossing Clarendon
Walk:	8 min	0.4 mi
Colonial Village Shopping Center
Walk:	12 min	0.6 mi
Avalon Courthouse Place has 2 shopping centers within 0.6 mile, which is about a 12-minute walk. The miles and minutes will be for the farthest away property.
Parks and Recreation			Distance
Fort Bennett Park and Palisades Trail
Drive:	3 min	1.1 mi
David M. Brown Planetarium
Drive:	5 min	1.7 mi
Cherry Valley Park
Drive:	5 min	1.9 mi
Fort C.F. Smith Park & Historic Site
Drive:	5 min	2.0 mi
Theodore Roosevelt Island Park
Drive:	7 min	3.6 mi
Avalon Courthouse Place has 5 parks within 3.6 miles, including Fort Bennett Park and Palisades Trail, David M. Brown Planetarium, and Fort C.F. Smith Park & Historic Site.
Hospitals			Distance
Capital Hospice
Drive:	6 min	2.4 mi
Virginia Hospital Center
Drive:	7 min	2.8 mi
MedStar Georgetown University Hospital
Drive:	8 min	3.0 mi
Avalon Courthouse Place has 3 hospitals within 3.0 miles, the nearest is Capital Hospice which is 2.4 miles away and a 6 minute drive.
Military Bases			Distance
Fort Myer
Drive:	5 min	2.3 mi
The Pentagon
Drive:	5 min	2.8 mi
Naval Observatory
Drive:	9 min	4.8 mi
Avalon Courthouse Place has 3 military bases within 4.8 miles, the nearest is Fort Myer which is 2.3 miles away and a 5 minute drive.
 
 
Reviews for Avalon Courthouse Place
2.5
Renter Rating
5 Stars
1
4 Stars
4
3 Stars
1
2 Stars
2
1 Star
5
Share details of your own experience with this property
Renter Reviews 13 Reviews
Avalon Courthouse Place Photos

Renovated Package II kitchen with white cabinetry, grey quartz countertops, grey subway tile backsplash, stainless steel appliances, and hard surface flooring


1BR Vacant

Renovated Package II kitchen and living room with hard surface flooring

Renovated Package II living room with hard surface flooring

Renovated Package II bedroom with hard surface flooring

Walk-in closet

Renovated Package II bath with white cabinetry, grey quartz countertops, and hard surface flooring

Renovated Package I kitchen with white cabinetry, granite countertops, stainless steel appliances, and hard surface flooring

Renovated Package I kitchen with white cabinetry, granite countertops, stainless steel appliances, and hard surface flooring

Models

1 Bedroom

1 Bedroom

1 Bedroom

1 Bedroom

1 Bedroom

1 Bedroom

Nearby Apartments
Within 50 Miles of Avalon Courthouse Place

View More Communities
Avalon at Arlington Square

2350 26th Ct

Arlington, VA 22206

$2,022 - $3,672
Total Monthly Price

1-3 Br
3.0 mi

Avalon at Foxhall

4100 Massachusetts Ave NW

Washington, DC 20016

$2,115 - $3,429

1-2 Br
3.1 mi

Avalon Potomac Yard

731 Seaton Ave

Alexandria, VA 22305

$2,416 - $4,337
Total Monthly Price

1-2 Br
12 Month Lease
4.5 mi

Avalon Falls Church

6600 Colton Crawford Cir

Falls Church, VA 22042

$2,352 - $5,047
Total Monthly Price

1-3 Br
4.6 mi

AVA Wheaton

2425 Blueridge Ave

Silver Spring, MD 20902

$1,625 - $3,020

1-3 Br
10.8 mi

Avalon at Traville

14240 Alta Oaks Dr

Rockville, MD 20850

$1,880 - $3,641

1-3 Br
15.3 mi

Frequently Asked Questions
Does Avalon Courthouse Place have in-unit laundry?
Avalon Courthouse Place has units with in‑unit washers and dryers, making laundry day simple for residents.

What utilities are included in rent at Avalon Courthouse Place?
Avalon Courthouse Place includes trash removal in rent. Residents are responsible for any other utilities not listed.

Is parking available at Avalon Courthouse Place?
Parking is available at Avalon Courthouse Place for $110 - $120 / mo. Contact this property for details.

Which floor plans are available, and what are the price ranges?
Avalon Courthouse Place has one to two-bedrooms with rent ranges from $2,321/mo. to $4,061/mo.

Is Avalon Courthouse Place pet-friendly?
Yes, Avalon Courthouse Place welcomes pets. Breed restrictions, weight limits, and additional fees may apply. View this property's pet policy.

How much income do I need to rent at Avalon Courthouse Place?
A good rule of thumb is to spend no more than 30% of your gross income on rent. Based on the lowest available rent of $2,321 for a one-bedroom, you would need to earn about $92,840 per year to qualify. Want to double-check your budget? Calculate how much rent you can afford with our Rent Affordability Calculator.

Does Avalon Courthouse Place have move-in specials?
Avalon Courthouse Place is offering Specials for eligible applicants, with rental rates starting at $2,321.

Does Avalon Courthouse Place offer Matterport 3D tours?
Yes! Avalon Courthouse Place offers 2 Matterport 3D Tours. Explore different floor plans and see unit level details, all without leaving home.

Report an Issue  Print  Get Directions 
Try These Popular Nearby Searches
Cities

Rosslyn Rentals
Seven Corners Rentals
Bailey's Crossroads Rentals
Lake Barcroft Rentals
Falls Church Rentals
 
Search by Bedrooms

Studio Apartments in Arlington
1 Bedroom Apartments in Arlington
2 Bedroom Apartments in Arlington
3 Bedroom Apartments in Arlington
Rooms for Rent in Arlington
Other Rental Types

Arlington Lofts for Rent
Arlington Houses for Rent
Arlington Condos for Rent
Arlington Townhomes for Rent
Private Landlord Rentals Arlington
Arlington Duplex Rentals
22201 Houses for Rent
22201 Condos for Rent
22201 Townhomes for Rent
 
Stay on Budget

Arlington Apartments Under $900
Arlington Apartments Under $1,000
Arlington Apartments Under $1,100
Arlington Apartments Under $1,200
Arlington Apartments Under $1,300
Arlington Apartments Under $1,400
Arlington Apartments Under $1,500
Arlington Apartments Under $2,000
 
Filter by Popular Amenities

Pet Friendly Apartments in Arlington
Furnished Apartments in Arlington
Apartments with Washer & Dryer in Arlington
Wheelchair Accessible Apartments in Arlington
Apartments with EV Charging in Arlington
Apartments with Balcony in Arlington
Apartments with Air Conditioning in Arlington
Arlington Apartments with Virtual Tours
 
Find Specialty Housing

Student Housing in Arlington
Arlington Low Income Housing
Senior Housing in Arlington
Short Term Rentals in Arlington
Luxury Apartments in Arlington
Cheap Apartments in Arlington
Corporate Housing in Arlington
Move-In Specials in Arlington
New Apartments in Arlington
About Us Advertise Legal Notices Privacy Notice Avoid Scams Accessibility Calculate Rent Affordability Renterverse Sitemap
apartments.com
© 2026 CoStar Group, Inc.
Equal Housing Opportunity

Apartments.com Ai

"""

for key, default in {
    "listing_text": "",
    "filtered_df": pd.DataFrame(),
    "comparison_df": pd.DataFrame(),
    "parsed_df": pd.DataFrame(),
    "last_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


st.markdown("""
<div class="hero">
    <h1>🏠 Nest AI</h1>
    <p>
    Find your next apartment in seconds. Compare floor plans, pricing,
    square footage, metro access, and amenities without building spreadsheets.
    </p>
</div>
""", unsafe_allow_html=True)

with st.expander("Why Nest AI?", expanded=True):
    st.write("""
Apartment hunting often means comparing dozens of tabs, prices, floor plans, fees, locations, and availability dates manually.

Nest AI turns unstructured Apartments.com listing text into structured, filterable, ranked recommendations — helping renters make faster, clearer decisions.
""")

st.info("""
🚀 **Try an example or get your own.**

Go to an Apartments.com listing, press **Ctrl + A**, then **Ctrl + C**, paste everything below, and let the magic happen.
""")

video_left, video_right = st.columns([0.45, 0.55])
with video_left:
    st.markdown("### 🎥 Quick Demo")
    if os.path.exists("C:\\Users\\smbro\\Videos\\Recording 2026-06-14 145634.mp4"):
        st.video("C:\\Users\\smbro\\Videos\\Recording 2026-06-14 145634.mp4")
def compute_best_deal_score(row):
    """
    Higher score = better deal.
    Simple MVP logic:
    - lower rent is better
    - higher square footage is better
    - sooner availability is better
    """
    rent = row.get("unit_price")
    sqft = row.get("unit_sqft")
    availability_dt = row.get("availability_dt")

    if pd.isna(rent) or pd.isna(sqft) or rent == 0:
        return None

    score = 0

    # Value from space relative to price
    score += (sqft / rent) * 10000

    # Bonus for sooner availability
    if pd.notna(availability_dt):
        days_until_available = (availability_dt - datetime.today()).days
        if days_until_available <= 0:
            score += 15
        elif days_until_available <= 7:
            score += 10
        elif days_until_available <= 30:
            score += 5

    return round(score, 2)


if "raw_text" not in st.session_state:
    st.session_state.raw_text = ""

if "parsed_listing" not in st.session_state:
    st.session_state.parsed_listing = None

if "comparison_rows" not in st.session_state:
    st.session_state.comparison_rows = []

if "ai_prefs" not in st.session_state:
    st.session_state.ai_prefs = None

if "ai_rationale" not in st.session_state:
    st.session_state.ai_rationale = ""


# -----------------------
# Header
# -----------------------
st.write("Turn copied apartment listing text into structured comparison data.")
st.caption("Built to save time and automate manual parsing of comparing apartment listings copied from restricted websites.")


# -----------------------
# Input / Parsed output
# -----------------------
left_col, right_col = st.columns([1, 1])

with left_col:
    st.subheader("Paste Listing Text")

    btn1, btn2, btn3 = st.columns(3)

    with btn1:
        if st.button("Load Sample 1"):
            st.session_state.raw_text = load_text_file("data/app_listing_1.txt")
            st.session_state.parsed_listing = None

    with btn2:
        if st.button("Load Sample 2"):
            st.session_state.raw_text = load_text_file("data/app_listing_2.txt")
            st.session_state.parsed_listing = None

    with btn3:
        if st.button("Clear Text"):
            st.session_state.raw_text = ""
            st.session_state.parsed_listing = None

    raw_text = st.text_area(
        "Paste apartment listing text here",
        value=st.session_state.raw_text,
        height=320,
        placeholder="Paste copied apartment listing text here...",
    )

    if st.button("Extract Data", type="primary"):
        if raw_text.strip():
            parsed = parse_apartment_listing(raw_text)
            st.session_state.parsed_listing = parsed
            st.session_state.raw_text = raw_text
        else:
            st.warning("Please paste text or load a sample listing first.")

with right_col:
    st.subheader("Extracted Listing Details")

    parsed_listing = st.session_state.parsed_listing

    if parsed_listing:
        st.write(f"**Property Title:** {parsed_listing.get('property_title') or 'N/A'}")
        st.write(f"**Floorplan Name:** {parsed_listing.get('floorplan_name') or 'N/A'}")
        st.write(f"**Beds:** {parsed_listing.get('beds') or 'N/A'}")
        st.write(f"**Baths:** {parsed_listing.get('baths') or 'N/A'}")
        st.write(f"**Floorplan Price Range:** {parsed_listing.get('floorplan_price_range') or 'N/A'}")
        st.write(f"**Floorplan Sq Ft Range:** {parsed_listing.get('floorplan_sqft_range') or 'N/A'}")
        st.write(f"**Has Den:** {'Yes' if parsed_listing.get('floorplan_has_den') else 'No'}")

        st.markdown("### Amenities")
        st.write(format_list_for_display(parsed_listing.get("amenities", [])))

        st.markdown("### Apartment Features")
        st.write(format_list_for_display(parsed_listing.get("apartment_features", [])))

        st.markdown("### Walkability")
        walkability = parsed_listing.get("walkability", {}) or {}
        st.write(
            f"**Walk Score:** "
            f"{walkability.get('walk_score') if walkability.get('walk_score') is not None else 'N/A'}"
            f"{f' ({walkability.get('walk_label')})' if walkability.get('walk_label') else ''}"
        )
        st.write(
            f"**Transit Score:** "
            f"{walkability.get('transit_score') if walkability.get('transit_score') is not None else 'N/A'}"
            f"{f' ({walkability.get('transit_label')})' if walkability.get('transit_label') else ''}"
        )
        st.write(
            f"**Bike Score:** "
            f"{walkability.get('bike_score') if walkability.get('bike_score') is not None else 'N/A'}"
            f"{f' ({walkability.get('bike_label')})' if walkability.get('bike_label') else ''}"
        )

        units = parsed_listing.get("units", [])
        st.write(f"**Units Parsed:** {len(units)}")

        if units:
            unit_df = pd.DataFrame(units)
            st.dataframe(unit_df, use_container_width=True)

            if st.button("Add Units to Comparison Table"):
                rows = build_comparison_rows(parsed_listing)
                st.session_state.comparison_rows.extend(rows)
                st.success(f"Added {len(rows)} unit rows to comparison table.")
        else:
            st.warning("No unit rows were parsed from this listing.")

        with st.expander("Show parsed JSON"):
            st.json(parsed_listing)
    else:
        st.caption("Add `demo.mp4` to this project folder to show your screen recording here.")

left, right = st.columns([1.15, 0.85], gap="large")

with left:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("1. Paste Listing Text")

    c1, c2 = st.columns(2)

    with c1:
        if st.button("🏢 Use Avalon Example", use_container_width=True):
            st.session_state.listing_text = AVALON_EXAMPLE
            st.rerun()

    with c2:
        if st.button("🧹 Clear Text", use_container_width=True):
            st.session_state.listing_text = ""
            st.session_state.last_result = None
            st.session_state.parsed_df = pd.DataFrame()
            st.rerun()

    listing_text = st.text_area(
        "Apartment listing text",
        key="listing_text",
        height=420,
        label_visibility="collapsed"
    )

    analyze = st.button("✨ Analyze Apartment", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)



if analyze:
    result = parse_apartment_text(st.session_state.listing_text)
    st.session_state.last_result = result
    st.session_state.parsed_df = pd.DataFrame(result["units"])


if st.session_state.last_result:
    result = st.session_state.last_result
    building = result.get("building_nearby", {})

    st.markdown("### 🏠 Property Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Property", result["property_title"] or "Unknown")
    m2.metric("Units Parsed", result["unit_count"])
    m3.metric("Nearest Metro", format_travel(building.get("metro_travel_mode"), building.get("metro_min")))
    m4.metric("Nearest Hospital", format_travel(building.get("hospital_travel_mode"), building.get("hospital_min")))

    st.caption(result["address"])

    if result.get("nearby_places"):
        with st.expander("View nearby building-level places"):
            st.dataframe(pd.DataFrame(result["nearby_places"]), use_container_width=True)

    if not st.session_state.parsed_df.empty:
        st.markdown("### 📋 Parsed Units")
        st.caption("Units extracted from the current building. Save them, then filter and rank below.")        
        st.dataframe(st.session_state.parsed_df, use_container_width=True)

        

        if st.button("➕ Save Units", use_container_width=True):
            st.session_state.comparison_df = pd.concat(
                [st.session_state.comparison_df, st.session_state.parsed_df],
                ignore_index=True
            )
            st.success("Units added!")
            st.rerun()
    else:
        st.warning("No unit rows were parsed from this listing.")



st.markdown("### 🔎 Filter & Rank Your Apartments")

if not st.session_state.comparison_df.empty:
    comp_df = st.session_state.comparison_df.copy()

    min_price = int(comp_df["price_num"].min())
    max_price = int(comp_df["price_num"].max())

    price_range = st.slider(
        "Monthly price range",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=50
    )

    min_sqft = int(comp_df["sqft_num"].min())
    max_sqft = int(comp_df["sqft_num"].max())

    sqft_range = st.slider(
        "Square footage range",
        min_value=min_sqft,
        max_value=max_sqft,
        value=(min_sqft, max_sqft),
        step=25
    )



    st.markdown("""
    <p class="small-muted">
    Try: “cheapest 1 bed available now” or “2 bed 2 bath within 10 min walk of metro.”
    </p>
    """, unsafe_allow_html=True)



    llm_request = st.text_input(
        "Ask Nest AI to filter your saved units",
        value="1 bed not on the first floor within 10 min walk of metro"
    )

    filtered_comp_df = comp_df[
        (comp_df["price_num"] >= price_range[0]) &
        (comp_df["price_num"] <= price_range[1]) &
        (comp_df["sqft_num"] >= sqft_range[0]) &
        (comp_df["sqft_num"] <= sqft_range[1])
    ]

    filtered_comp_df = filter_units_by_request(filtered_comp_df, llm_request)

    st.markdown("### 🏆 Nest AI Recommendations: Compare all your saved units to see what fits your pesonalized needs")

    if filtered_comp_df.empty:
        st.warning("No saved units match your filters.")
    else:
        ranked_df = filtered_comp_df.copy()

        ranked_df["price_score"] = ranked_df["price_num"].rank(ascending=False)
        ranked_df["space_score"] = ranked_df["sqft_num"].rank(ascending=True)

        if "metro_min" in ranked_df.columns:
            ranked_df["metro_score"] = ranked_df["metro_min"].fillna(99).rank(ascending=False)
        else:
            ranked_df["metro_score"] = 0

        ranked_df["floor_score"] = ranked_df["floor"].fillna(0).rank(ascending=True)

        ranked_df["nest_score"] = (
            ranked_df["price_score"] * 0.35 +
            ranked_df["space_score"] * 0.30 +
            ranked_df["metro_score"] * 0.25 +
            ranked_df["floor_score"] * 0.10
        )

        ranked_df = ranked_df.sort_values("nest_score", ascending=False)

        top3 = ranked_df.head(3)

        for i, (_, row) in enumerate(top3.iterrows(), start=1):
            st.success(
                f"#{i} • {row.get('property', 'Unknown')} • Unit {row.get('unit', 'N/A')}  \n"
                f"${int(row.get('price_num', 0)):,} • {int(row.get('sqft_num', 0))} sqft • "
                f"{row.get('beds', '')} • {row.get('baths', '')}"
            )

        display_cols = [
            "property",
            "floorplan",
            "unit",
            "floor",
            "price",
            "beds",
            "baths",
            "sqft",
            "has_den",
            "availability",
            "nearest_metro",
            "metro_travel_mode",
            "metro_min",
            "nearest_hospital",
            "hospital_travel_mode",
            "hospital_min",
            "nest_score",
        ]

        display_cols = [col for col in display_cols if col in ranked_df.columns]
        clean_ranked_df = ranked_df[display_cols].copy()

        if "nest_score" in clean_ranked_df.columns:
            clean_ranked_df["nest_score"] = clean_ranked_df["nest_score"].round(2)

        st.dataframe(clean_ranked_df, use_container_width=True)
else:
    st.info("Add units to compare first.")
