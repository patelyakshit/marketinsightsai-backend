"""
Esri GeoEnrichment API Service

Provides access to tapestry segment data from Esri's GeoEnrichment API
and includes static segment profile data for AI context and report enrichment.

Data source: ArcGIS Tapestry 2025 (Esri Demographics)
https://doc.arcgis.com/en/esri-demographics/latest/esri-demographics/tapestry-segmentation.htm
"""
import json
import httpx
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from app.config import get_settings

settings = get_settings()

# In-memory cache for API responses
_enrichment_cache: dict[str, tuple[dict, datetime]] = {}


class SegmentProfile(BaseModel):
    """Full tapestry segment profile."""
    code: str
    number: int
    name: str
    life_mode: str
    life_mode_code: str
    description: str
    median_age: Optional[float] = None
    median_household_income: Optional[float] = None
    median_net_worth: Optional[float] = None
    median_home_value: Optional[float] = None
    homeownership_rate: Optional[float] = None
    bachelors_degree_rate: Optional[float] = None


class EnrichmentResult(BaseModel):
    """Result from enriching a location with Esri data."""
    dominant_segment_code: str
    dominant_segment_name: str
    total_population: Optional[int] = None
    total_households: Optional[int] = None
    median_age: Optional[float] = None
    segments: list[dict] = []


# =============================================================================
# ArcGIS Tapestry 2025 Segment Data
# 60 distinct segments organized into 12 LifeMode groups (A-L)
# Data sourced from: doc.arcgis.com/en/esri-demographics/latest/esri-demographics/
# =============================================================================

SEGMENT_PROFILES: dict[str, dict] = {
    # =========================================================================
    # LifeMode A: Urban Threads
    # =========================================================================
    "A1": {
        "number": 1,
        "name": "Independent Cityscapes",
        "life_mode": "Urban Threads",
        "life_mode_code": "A",
        "description": "Members of these communities often reside in the centers of large metropolitan cities in the South and Midwest, with many also living in the suburbs. Households are mainly single individuals, female single parents raising young children, or family households without couples or children. Over half of individuals have never married, and divorce rates are high among those who have. More than half of households earn low-tier incomes, often supported by social security and other forms of public assistance. Most residents are employed at workplaces within a half-hour commute, and driving is the primary means of commuting. Housing units are typically older low-rise and high-rise apartments built before 1990. Rent is low relative to the national average, as are home values.",
        "median_age": 39.3,
        "median_household_income": 26555,
        "median_net_worth": 11000,
        "median_home_value": 152321,
        "homeownership_rate": 0.236,
        "bachelors_degree_rate": 0.161,
    },
    "A2": {
        "number": 2,
        "name": "City Commons",
        "life_mode": "Urban Threads",
        "life_mode_code": "A",
        "description": "These neighborhoods are typically located in and around the centers of metropolitan cities in the South and Midwest. This segment is the youngest outside of communities centered on colleges and military facilities, and it ranks highest in the presence of single-parent families as well as children under age 6. Many individuals hold full-time jobs in the service sector, though part-time work is also common. Most households earn low- to middle-tier incomes and are often supported by social security and other forms of public assistance. Neighborhoods typically include a mix of low-rise multiunit dwellings and single-family homes, with more than half built before 1970. Rents are low compared to the national average, though many renters spend over 35 percent of their income on rent and utilities.",
        "median_age": 29.1,
        "median_household_income": 27823,
        "median_net_worth": 11213,
        "median_home_value": 119791,
        "homeownership_rate": 0.204,
        "bachelors_degree_rate": 0.123,
    },
    "A3": {
        "number": 3,
        "name": "Social Security Set",
        "life_mode": "Urban Threads",
        "life_mode_code": "A",
        "description": "These neighborhoods are primarily located in the downtown urban cores of the largest metropolitan areas, and residents often live in low-rent, older high-rise buildings near centers of economic activity with heavy daytime traffic. The population is older, often widowed or divorced, and there is a higher proportion of single-person households in these communities than any other segment. Rates of recent immigration are high, and many speak a language other than English as their first language. Income disparities are notable, with many residents supported by social security and other forms of public assistance, while a significant portion of the population earns middle-tier incomes. Homeowners spend a large portion of their income on housing costs, and many households do not own a vehicle.",
        "median_age": 49.5,
        "median_household_income": 31425,
        "median_net_worth": 15000,
        "median_home_value": 333286,
        "homeownership_rate": 0.166,
        "bachelors_degree_rate": 0.304,
    },
    "A4": {
        "number": 4,
        "name": "Fresh Ambitions",
        "life_mode": "Urban Threads",
        "life_mode_code": "A",
        "description": "These communities are concentrated in the Mid-Atlantic and Pacific regions, and they comprise large families, including single parents and married or cohabiting couples, often helped by grandparents. About one-third of the population is under 20, and the child dependency ratio is among the highest in the nation. Residents tend to work in skilled and service jobs, and incomes primarily range from low- to middle-tier. These communities' living arrangements vary widely, including smaller multi-family buildings, single-family homes, and row or townhomes, many built before 1950. Despite varied housing types, they tend to share an urban lifestyle, with nearly half residing in urban centers or suburbs. Although average rents are below the national level, many face a high rental burden.",
        "median_age": 31.3,
        "median_household_income": 41775,
        "median_net_worth": 25000,
        "median_home_value": 173878,
        "homeownership_rate": 0.292,
        "bachelors_degree_rate": 0.121,
    },
    "A5": {
        "number": 5,
        "name": "Welcome Waves",
        "life_mode": "Urban Threads",
        "life_mode_code": "A",
        "description": "Neighborhoods in this segment are concentrated in the centers and nearby suburbs of mega metropolises, predominantly in the South and West. These communities are home to many young individuals and families born outside the U.S. Roughly half of families have multiple working adults, and households generally earn low- to middle-tier incomes. Workers tend to be employed in construction, manufacturing, retail, food service, and accommodations jobs, and carpooling, biking, or walking to work is common. Residents primarily live in moderately dense residential areas with mid- to high-rise buildings, most of which were built before 1990. While rental prices are below the national average, rents remain high relative to income.",
        "median_age": 30.0,
        "median_household_income": 50427,
        "median_net_worth": 30000,
        "median_home_value": 276278,
        "homeownership_rate": 0.160,
        "bachelors_degree_rate": 0.156,
    },
    "A6": {
        "number": 6,
        "name": "Young and Restless",
        "life_mode": "Urban Threads",
        "life_mode_code": "A",
        "description": "These communities are predominantly composed of young residents living in and around urban centers in mega metropolitan areas in the South, Midwest, and West. Many householders are under 35 and live alone, with roommates, or as cohabiting couples without children. Neighborhoods are culturally diverse with a significant portion of the population born outside the U.S. Many residents hold a bachelor's degree or are currently enrolled in college. This segment has one of the highest labor force participation rates in the country, and the majority of residents earn middle-tier incomes. Residents tend to be highly mobile, frequently relocating for housing and employment opportunities. Housing is primarily located away from the main downtown area in small multifamily apartments or high-rise buildings, and most workers have short commutes.",
        "median_age": 31.4,
        "median_household_income": 56258,
        "median_net_worth": 25000,
        "median_home_value": 287356,
        "homeownership_rate": 0.049,
        "bachelors_degree_rate": 0.370,
    },

    # =========================================================================
    # LifeMode B: Campus Connections
    # =========================================================================
    "B1": {
        "number": 7,
        "name": "Dorms to Diplomas",
        "life_mode": "Campus Connections",
        "life_mode_code": "B",
        "description": "These neighborhoods are found in the centers and suburbs of metropolitan areas, with a notable presence in cities of 100,000 to 500,000 people. The residents in this segment represent the youngest demographic among all Tapestry segments. They are pursuing bachelor's and graduate degrees, and they are mostly unmarried and in their late teens to early 20s. Part-time employment in service occupations is common, and employment varies widely, including government, education, food and accommodation, service, and retail sectors. Housing for this segment is a blend of on-campus and off-campus living. Most reside in multiunit buildings with five or more units, such as dormitories or apartments, featuring a mix of old and new housing.",
        "median_age": 21.8,
        "median_household_income": 29081,
        "median_net_worth": 9563,
        "median_home_value": 332446,
        "homeownership_rate": 0.070,
        "bachelors_degree_rate": 0.580,
    },
    "B2": {
        "number": 8,
        "name": "College Towns",
        "life_mode": "Campus Connections",
        "life_mode_code": "B",
        "description": "Communities in this segment are spread across the country and are most often located in and around city centers and in the suburbs. Neighborhoods are frequently located in the largest metropolitan areas, but there is a significant presence in smaller cities of 100,000 to 250,000 people. These residents are a mix of students and individuals affiliated with universities. Actively enrolled students constitute nearly half of the population, with many having recently moved to the U.S. Nearly half of the population holds a bachelor's or graduate degree. Part-time work is common, often within biking or walking distance, in jobs linked to colleges or supporting industries like food service and accommodations. Rates of government employment are also high. Around three-quarters of residents are renters, and on-campus and multifamily housing is typical.",
        "median_age": 24.6,
        "median_household_income": 46253,
        "median_net_worth": 13771,
        "median_home_value": 293431,
        "homeownership_rate": 0.253,
        "bachelors_degree_rate": 0.496,
    },
    "B3": {
        "number": 9,
        "name": "Military Proximity",
        "life_mode": "Campus Connections",
        "life_mode_code": "B",
        "description": "These small communities are typically located in suburban regions near military facilities, with the highest concentrations in the South and West. This segment primarily consists of young, married couples, with or without children, as well as nonfamily and single-parent households. Many in this segment are affiliated with the military and work full-time. Government and federal employment rank higher than in any other segment. Many have completed some college or earned an associate degree; the proportion of individuals with bachelor's or graduate degrees is relatively low. Residents tend to move frequently and rent subsidized housing in relatively new developments. The daytime population is significantly higher than the national average due to the presence of armed forces personnel both on and off bases.",
        "median_age": 22.9,
        "median_household_income": 71464,
        "median_net_worth": 17514,
        "median_home_value": 376119,
        "homeownership_rate": 0.032,
        "bachelors_degree_rate": 0.347,
    },

    # =========================================================================
    # LifeMode C: Diverse Pathways
    # =========================================================================
    "C1": {
        "number": 10,
        "name": "Single Thrifties",
        "life_mode": "Diverse Pathways",
        "life_mode_code": "C",
        "description": "Residents in this segment mostly live in or near large and midsized metropolitan areas in the Midwest and South. They are predominantly in their 20s and 30s, with households comprising singles, couples without children, and nonfamily members. These neighborhoods experience moderate growth and high mobility. A notable portion are recent immigrants. One in three individuals have completed high school, and another third are pursuing higher education, often supported by part-time jobs. Most live alone, renting property in duplexes and small apartment complexes built before 1990. They pay below the national average for rent. Employment is prevalent in retail, health, food service, and manufacturing industries. Commutes are short and workers often drive alone, but many also carpool, bike, or walk to work.",
        "median_age": 37.0,
        "median_household_income": 47084,
        "median_net_worth": 35000,
        "median_home_value": 174373,
        "homeownership_rate": 0.357,
        "bachelors_degree_rate": 0.200,
    },
    "C2": {
        "number": 11,
        "name": "Kids and Kin",
        "life_mode": "Diverse Pathways",
        "life_mode_code": "C",
        "description": "Neighborhoods in this segment are largely found in and around metropolitan areas with populations exceeding half a million. Householders are generally under the age of 54 and may have adult children living with parents at home. The majority of the population aged 25 and above have a high school diploma, an associate degree, or some college education. Jobs are often in the health care, retail, food, manufacturing, and transportation sectors; there is a high level of female labor force participation. Residents live in older homes, usually as renters, with a notable presence of town homes and smaller low-rise rental buildings. On average, homes are modestly priced and affordable for most households. Suburban residents rely on vehicles to get to work, while those in and near cities use public transportation.",
        "median_age": 33.3,
        "median_household_income": 50960,
        "median_net_worth": 40000,
        "median_home_value": 201173,
        "homeownership_rate": 0.392,
        "bachelors_degree_rate": 0.220,
    },
    "C3": {
        "number": 12,
        "name": "Metro Fusion",
        "life_mode": "Diverse Pathways",
        "life_mode_code": "C",
        "description": "These neighborhoods are concentrated in densely populated metropolitan areas of between 500,000 and 2.5 million people. This is a highly mobile population that frequently moves within the same area. Household structure varies widely, from young householders under the age of 35 with preschool-aged children to renters living alone or as couples without children. More than half of this segment is either in college or holds an associate degree or higher; they earn middle-tier incomes in the retail, health care, and food service sectors. They live in mid- to high-rise multifamily structures or older homes valued under $300,000; some occupy single-family homes. Households generally own at least one car, typically a used vehicle, and commute times are typically under half an hour.",
        "median_age": 32.8,
        "median_household_income": 55443,
        "median_net_worth": 45000,
        "median_home_value": 242615,
        "homeownership_rate": 0.244,
        "bachelors_degree_rate": 0.350,
    },
    "C4": {
        "number": 13,
        "name": "Family Foundations",
        "life_mode": "Diverse Pathways",
        "life_mode_code": "C",
        "description": "Residents in this segment reside largely in suburbs in the South, and many commute to another county for work. Most households are occupied by a single person, a married couple without children, or a combined family without couples or children. Adult children living with their parents are not uncommon; there is a higher rate of multigenerational households. There are more female than male householders. Many residents have some college education, though high school completion rates are lower than the national average. Most households earn middle-tier incomes and employment is largely in government, health care, and retail sectors. Social security and other forms of public assistance are key sources of support. Residents typically own homes built before 1990, with most valued under $200,000.",
        "median_age": 41.0,
        "median_household_income": 58089,
        "median_net_worth": 75000,
        "median_home_value": 183266,
        "homeownership_rate": 0.656,
        "bachelors_degree_rate": 0.180,
    },
    "C5": {
        "number": 14,
        "name": "Diverse Horizons",
        "life_mode": "Diverse Pathways",
        "life_mode_code": "C",
        "description": "Members of these communities, many of whom were born outside the U.S., live in and around metropolitan areas with populations exceeding 2.5 million, commonly located along interstate corridors and on the coasts. Families tend to be large, and a sizable proportion of the population consists of children. Nonfamily households, including individuals living alone, represent about a third of this segment. Residents often work in service and skilled occupations with middle-tier incomes compared to the national average. Parking constraints often limit households to one or two vehicles. There are low levels of housing affordability and members reside in predominantly rental neighborhoods of multiunit structures, many of which were built before 1990. Commuters often use public transportation.",
        "median_age": 35.2,
        "median_household_income": 65990,
        "median_net_worth": 55000,
        "median_home_value": 396119,
        "homeownership_rate": 0.365,
        "bachelors_degree_rate": 0.250,
    },
    "C6": {
        "number": 15,
        "name": "Moderate Metros",
        "life_mode": "Diverse Pathways",
        "life_mode_code": "C",
        "description": "These neighborhoods are young, growing, and usually located in suburbs and the peripheries of metropolitan areas with relatively dense populations of at least half a million. Single-person households make up about one-third of total households, followed by married, cohabiting, or single persons with children. There is an above-average presence of preschool-age children. Many have attended some college, and individuals often work in health care, retail, office/administration, or sales. Household incomes generally fall within the middle tier. The typical home for this segment is a moderately priced ($200-500K) single-family residence built before the 90s; about half are rented and half are owned. Commute times are generally low and driven alone.",
        "median_age": 38.1,
        "median_household_income": 70055,
        "median_net_worth": 85000,
        "median_home_value": 313879,
        "homeownership_rate": 0.541,
        "bachelors_degree_rate": 0.280,
    },

    # =========================================================================
    # LifeMode D: Ambitious Singles
    # =========================================================================
    "D1": {
        "number": 16,
        "name": "Emerging Hub",
        "life_mode": "Ambitious Singles",
        "life_mode_code": "D",
        "description": "Members of these communities are young, live in cities, and move frequently. These neighborhoods show consistent growth and are composed of large numbers of young graduates and college students who have relocated to the U.S. Most individuals live alone, though some share their homes with roommates or partners. Most earn middle-tier incomes and are employed in full-time professional occupations such as management, finance, computer science, engineering, education, and health care; the rate of remote work is higher than average. Housing options are a mix of single-family and multifamily units. Frequent relocations occur both within and outside the county, and rents are on par with the national average. While owning a vehicle is considered necessary, biking or walking to nearby schools and workplaces is an option.",
        "median_age": 36.0,
        "median_household_income": 70356,
        "median_net_worth": 58291,
        "median_home_value": 369687,
        "homeownership_rate": 0.327,
        "bachelors_degree_rate": 0.516,
    },
    "D2": {
        "number": 17,
        "name": "Trendsetters",
        "life_mode": "Ambitious Singles",
        "life_mode_code": "D",
        "description": "Nearly all residents in this segment reside in or near metropolitan areas with dense urban populations exceeding 2.5 million. Half of the segment is aged 25 to 44 and many are unmarried. Bachelor's and graduate degrees are common, and most have completed at least some college education. More than a quarter of the population was born outside the U.S., with many having immigrated in the last decade. Many are employed in professional jobs in industries like technology, health care, and education. Some work from home. Most homes are rented, many in multiunit structures. Of the homes that are owned, nearly three-quarters are valued over $500,000. Over half of workers have lengthy commutes of at least 30 minutes, and use of public transportation is common.",
        "median_age": 37.4,
        "median_household_income": 86061,
        "median_net_worth": 69698,
        "median_home_value": 741526,
        "homeownership_rate": 0.257,
        "bachelors_degree_rate": 0.524,
    },
    "D3": {
        "number": 18,
        "name": "Modern Minds",
        "life_mode": "Ambitious Singles",
        "life_mode_code": "D",
        "description": "This fast-growing segment is primarily located just outside downtown sections of large cities or in nearby suburbs. Residents are mostly in the 25 to 44 age range, and nearly half of individuals aged 25 and older hold a bachelor's degree. The segment has grown due to recent immigration, adding to the notable population of individuals born outside the U.S. already living here. Key employment sectors include health care, technology, retail, education, and manufacturing, and incomes often fall in the upper tier. The segment is a mix of homeowners and renters, residing in both single-family and multifamily units. Homes are generally newer, and two-thirds of owned homes are valued above $300,000. Households typically own multiple vehicles. While many have the option to work from home, most commute by car.",
        "median_age": 34.6,
        "median_household_income": 91039,
        "median_net_worth": 121498,
        "median_home_value": 429764,
        "homeownership_rate": 0.414,
        "bachelors_degree_rate": 0.496,
    },
    "D4": {
        "number": 19,
        "name": "Metro Renters",
        "life_mode": "Ambitious Singles",
        "life_mode_code": "D",
        "description": "Located mainly in the centers of major metropolitan areas, these neighborhoods are composed of highly educated young professionals in their 20s and 30s, many of whom were born outside the U.S. Residents often live alone, cohabitate with partners, or share space with roommates. The majority hold a bachelor's degree or higher, and a significant portion are enrolled in college. They work in professional or management positions with upper-tier incomes. Most homes are rented in buildings with 20 or more units, many of which have been constructed since 2010. Working from home is common. These areas also experience significant daytime population growth as hubs for workplaces, restaurants, and entertainment. Walking, ridesharing, or public transportation are common for commuting.",
        "median_age": 32.9,
        "median_household_income": 94766,
        "median_net_worth": 51079,
        "median_home_value": 566069,
        "homeownership_rate": 0.158,
        "bachelors_degree_rate": 0.736,
    },
    "D5": {
        "number": 20,
        "name": "Laptops and Lattes",
        "life_mode": "Ambitious Singles",
        "life_mode_code": "D",
        "description": "These neighborhoods are located in and around the largest, most densely populated metropolises in the country. Residents are young, and many live alone, with roommates, or as unmarried couples. One in three individuals aged 25 and older holds a graduate degree. They work in management, business, and computer-related fields in the technology, finance, health, and education sectors and earn upper-tier incomes. They may also make money through investments, rental properties, or operating their own businesses. Members of this segment generally rent property in mid- to high-rise buildings, with a mix of new construction and renovated units built before 1950. This is the most expensive market to rent or own housing relative to typical incomes. Commutes are often long; this segment ranks the highest for remote working.",
        "median_age": 36.2,
        "median_household_income": 145759,
        "median_net_worth": 233707,
        "median_home_value": 918816,
        "homeownership_rate": 0.359,
        "bachelors_degree_rate": 0.786,
    },

    # =========================================================================
    # LifeMode E: Mixed Mosaic
    # =========================================================================
    "E1": {
        "number": 21,
        "name": "Modest Income Homes",
        "life_mode": "Mixed Mosaic",
        "life_mode_code": "E",
        "description": "These neighborhoods are situated throughout the Midwest and South, with most residents living in and around urban centers and in the suburbs. Many households consist of married couples without children or single-parent, female-headed households. A substantial number are single individuals living alone, and a significant portion of the population is under 18. Household income is distributed across low and middle tiers, with most households earning under $50,000 annually. Many working-age residents are employed in food preparation, health-care support, building maintenance, production, or transportation and material moving occupations. A significant number of homes were built before 1970, and there is a notable percentage of unoccupied properties. Most properties are valued under $100,000.",
        "median_age": 37.1,
        "median_household_income": 35121,
        "median_net_worth": 18675,
        "homeownership_rate": 0.469,
        "bachelors_degree_rate": 0.120,
    },
    "E2": {
        "number": 22,
        "name": "Southwestern Families",
        "life_mode": "Mixed Mosaic",
        "life_mode_code": "E",
        "description": "Households in these neighborhoods are primarily young families located in and around urban centers and suburbs in the Southwest. These households are mainly composed of married couples or single-parent families, and this segment includes a significant share of multigenerational households, including adult children living with parents. Communities are culturally diverse, with many residents born outside of the U.S. Incomes are split between low and middle tiers, often supported by social security and other forms of public assistance. The working-age population is largely employed in office administrative support, services, construction, or building maintenance occupations. Houses are mainly single-family detached dwellings built before 1970. Half of all homes are owned, and a quarter of homeowners have a mortgage.",
        "median_age": 36.7,
        "median_household_income": 44023,
        "median_net_worth": 58547,
        "homeownership_rate": 0.582,
        "bachelors_degree_rate": 0.140,
    },
    "E3": {
        "number": 23,
        "name": "Hometown Charm",
        "life_mode": "Mixed Mosaic",
        "life_mode_code": "E",
        "description": "These communities are generally found in the suburbs or urban centers of metropolitan areas in the Midwest and South, though there is also a notable presence in more rural small towns. Neighborhoods are characterized by young families with children under 18. At least a third of households are nonfamily households, and marriage rates are comparatively lower than the national average, with more individuals never having been married. Employment is primarily in manufacturing, retail, health care, food, and accommodation. About a third of households earn low-tier incomes and are supported by social security and other forms of public assistance. Homes are typically single-family units and small apartment complexes, with over half built before 1970, and vacancy rates are relatively high.",
        "median_age": 35.7,
        "median_household_income": 50994,
        "median_net_worth": 60861,
        "homeownership_rate": 0.525,
        "bachelors_degree_rate": 0.180,
    },
    "E4": {
        "number": 24,
        "name": "Mobile Meadows",
        "life_mode": "Mixed Mosaic",
        "life_mode_code": "E",
        "description": "These neighborhoods are predominantly found in metropolitan and micropolitan areas. Around half of this segment's population resides in the South, with another third in the West. A steady influx of immigration contributes to cultural diversity in these communities, and job opportunities are primarily found in manufacturing, construction, and mining. Married and cohabiting couples outnumber single-individual households, and around a third of households have children. Incomes predominantly fall within the low to middle tiers, with some households supported by social security and other forms of public assistance. Homes in these neighborhoods are primarily mobile homes. Vehicles are a necessary part of everyday life, and abundant open space often surrounds these communities, contributing to a population density of less than 100 people per square mile.",
        "median_age": 35.1,
        "median_household_income": 54988,
        "median_net_worth": 106219,
        "homeownership_rate": 0.643,
        "bachelors_degree_rate": 0.150,
    },
    "E5": {
        "number": 25,
        "name": "Rural Versatility",
        "life_mode": "Mixed Mosaic",
        "life_mode_code": "E",
        "description": "These neighborhoods are predominantly found in rural and non-metro areas. About a quarter of the population in this segment is under 18, and around a third of households consist of seniors supported by social security and retirement income. More than half of households are occupied by either a single person or a married couple without children. Employment in manufacturing, construction, agriculture, and mining is more common than in most other markets, and full-time work is much more common than part-time. Public transportation is often not an option, and most workers commute by driving alone. Homes in this market are typically valued under $250,000 and are largely single-family detached units, though mobile homes are also common, and most homes are owned.",
        "median_age": 38.9,
        "median_household_income": 58911,
        "median_net_worth": 126005,
        "homeownership_rate": 0.667,
        "bachelors_degree_rate": 0.160,
    },
    "E6": {
        "number": 26,
        "name": "Family Bonds",
        "life_mode": "Mixed Mosaic",
        "life_mode_code": "E",
        "description": "Residents in this segment typically live in and around urban centers and in suburbs in the South and West. The population is younger and has larger family sizes than the U.S. average, and households typically include parents supporting young children, adult children living with parents, and other multigenerational family structures. Single-parent families and households without couples or children are also notably common. One in five residents were born outside the U.S., and the rate of linguistic isolation is more than twice the national average. Employment tends to be in skilled and service-related sectors, including construction, and households typically earn middle-tier incomes. Homes tend to be owner-occupied, single-family detached units built before 1990, with most valued between $100-300,000. The housing market is characterized by low vacancy rates and moderately high rents.",
        "median_age": 35.5,
        "median_household_income": 72515,
        "median_net_worth": 177755,
        "homeownership_rate": 0.689,
        "bachelors_degree_rate": 0.200,
    },

    # =========================================================================
    # LifeMode F: Metro Mix
    # =========================================================================
    "F1": {
        "number": 27,
        "name": "High Rise Renters",
        "life_mode": "Metro Mix",
        "life_mode_code": "F",
        "description": "Found mainly in the Northeast, these neighborhoods are among the highest in population density and are located in the urban centers of major hubs, such as New York City. These residents are typically young, and households include a mix of single-person households, married couples, and nontraditional households. Multigenerational and female-headed, single-parent households are also common. Many residents were born outside the U.S., and rates of linguistic isolation are high. Households typically earn low-tier incomes, often supported by social security and other forms of public assistance. Employment is common in administrative support roles or service professions. Most residents are renters living in high-rise apartments built around the 1950s or earlier. While rents are lower than the national average, they still represent a significant portion of residents' budgets.",
        "median_age": 35.7,
        "median_household_income": 37607,
        "median_net_worth": 12087,
        "homeownership_rate": 0.057,
        "bachelors_degree_rate": 0.280,
    },
    "F2": {
        "number": 28,
        "name": "Family Extensions",
        "life_mode": "Metro Mix",
        "life_mode_code": "F",
        "description": "These neighborhoods are typically found in large, densely populated metro areas particularly on the West Coast and are characterized by large, young families, often in multigenerational households. Many residents were born outside the U.S., and rates of linguistic isolation are high. Households typically earn low- to middle-tier incomes, with some supported by social security and other forms of public assistance. Employment is spread across various industries such as construction, accommodations and food services, health care, manufacturing, and transportation. Housing costs are high due to elevated property values and rent prices, and vacancy rates are low. Almost half of all dwellings are single-family detached or attached homes, while the rest are multiunit buildings, and most residents rent their homes. Commute times are relatively long.",
        "median_age": 32.7,
        "median_household_income": 67912,
        "median_net_worth": 52639,
        "homeownership_rate": 0.321,
        "bachelors_degree_rate": 0.250,
    },
    "F3": {
        "number": 29,
        "name": "Downtown Melting Pot",
        "life_mode": "Metro Mix",
        "life_mode_code": "F",
        "description": "These communities tend to be located in the urban centers of metropolitan cities, particularly in the Mid-Atlantic and Pacific regions, as well as New York City. Households are often multigenerational and composed of married-couple families with or without children. Nearly half of residents were born outside the U.S., and nearly one-third of the population speaks a language other than English as their first language. Households typically earn low- to middle-tier incomes, and some are supported by social security and other forms of public assistance. Roughly half of residents have some college education or a bachelor's degree or higher. A vast majority of residents are renters; for homeowners, property values are more than twice the U.S. median. More than a third of the population relies on public transportation, and most households have either one car or none at all.",
        "median_age": 38.1,
        "median_household_income": 70028,
        "median_net_worth": 64718,
        "homeownership_rate": 0.324,
        "bachelors_degree_rate": 0.300,
    },
    "F4": {
        "number": 30,
        "name": "City Strivers",
        "life_mode": "Metro Mix",
        "life_mode_code": "F",
        "description": "These neighborhoods are among the most densely populated, often located in and around urban centers and in the suburbs of major metropolises such as New York, Boston, Washington, D.C., and Chicago. The population is young, and many residents were born outside the U.S. The community is a blend of family households, married couples, single parents with younger or adult children, and single-person households. A sizable proportion of households are multigenerational. Households typically earn middle-tier incomes, and some are supported by social security and other forms of public assistance. More than half of individuals have some college education or have completed a degree. Residents work in a variety of professional and service jobs, and nearly a quarter commute 60 minutes or more.",
        "median_age": 38.5,
        "median_household_income": 76919,
        "median_net_worth": 102849,
        "homeownership_rate": 0.437,
        "bachelors_degree_rate": 0.320,
    },
    "F5": {
        "number": 31,
        "name": "Uptown Lights",
        "life_mode": "Metro Mix",
        "life_mode_code": "F",
        "description": "Located in both dense urban areas and suburbs of major metropolitan regions on both U.S. coasts, particularly in California, New York, New Jersey, and Washington, D.C., these neighborhoods are a mix of married couples, singles, and families, some with older children. Most have attended college or earned a degree, and household incomes are primarily in the middle tier. Employment is in a wide array of professional and service occupations, and some residents are self-employed. Approximately half of all homes are rented, with most residences constructed before the 1990s and a significant portion built before 1970. Most residents live in a mix of single-family detached homes, townhomes, or multiunit structures, and daily commutes are often 30 minutes or more.",
        "median_age": 38.7,
        "median_household_income": 101720,
        "median_net_worth": 206302,
        "homeownership_rate": 0.501,
        "bachelors_degree_rate": 0.450,
    },

    # =========================================================================
    # LifeMode G: Family Matters
    # =========================================================================
    "G1": {
        "number": 32,
        "name": "Shared Roots",
        "life_mode": "Family Matters",
        "life_mode_code": "G",
        "description": "These communities are mostly located in suburban, and sometimes urban, regions in the South and West. Large households are common, with one in three individuals under 18 years old and nearly half of families having children. There is a significant number of young households, adult children living with parents, and multigenerational families. Approximately one in three residents were born outside the U.S. Employment is common in skilled and service occupations, with key industries being construction, manufacturing, retail trade, and agriculture. Most households earn low- to middle-tier incomes. Housing is relatively affordable, featuring a mix of old and new owner-occupied and renter-occupied homes, with a notable presence of single-family units and mobile homes. Families often have multiple vehicles, and most commutes are under 30 minutes.",
        "median_age": 30.4,
        "median_household_income": 59647,
        "median_net_worth": 97589,
        "homeownership_rate": 0.604,
        "bachelors_degree_rate": 0.180,
    },
    "G2": {
        "number": 33,
        "name": "Up and Coming Families",
        "life_mode": "Family Matters",
        "life_mode_code": "G",
        "description": "Residents in this segment tend to live in suburban neighborhoods in the South, particularly in Texas, Georgia, Florida, and North Carolina. These are large, young families in a variety of household structures: married couples, both with and without children, make up about half of the households, with significant numbers of single-parent households, cohabiting couples with kids, and multigenerational families. Nearly one in three members of this segment hold a bachelor's or graduate degree. Key employment sectors include health care, retail, education, manufacturing, and construction. There are many first-time homebuyers, and homeowners outnumber renters. Approximately half of homes in this segment were constructed in the last 5 to 10 years. Residents often commute longer distances, frequently outside their county of residence.",
        "median_age": 33.6,
        "median_household_income": 89093,
        "median_net_worth": 247071,
        "homeownership_rate": 0.731,
        "bachelors_degree_rate": 0.350,
    },
    "G3": {
        "number": 34,
        "name": "Generational Ties",
        "life_mode": "Family Matters",
        "life_mode_code": "G",
        "description": "These communities consist of large, multigenerational families residing mostly in suburbs in the West, particularly in California, with notable populations in Florida and New York. Average family sizes exceed 3.5 people, the highest in the nation. Children are present in a third of households, including adult children living at home. One in three individuals was born outside the U.S. Nearly half of this segment has some college education, and workers typically hold jobs in health care, retail trade, manufacturing, construction, and transportation that provide middle-tier incomes. They reside in older single-family homes, with much of the housing built before 1970. For nearly a third of households that rent, rental prices are significantly higher than the national average.",
        "median_age": 36.9,
        "median_household_income": 95282,
        "median_net_worth": 298163,
        "homeownership_rate": 0.718,
        "bachelors_degree_rate": 0.320,
    },

    # =========================================================================
    # LifeMode H: Suburban Style
    # =========================================================================
    "H1": {
        "number": 35,
        "name": "Flourishing Families",
        "life_mode": "Suburban Style",
        "life_mode_code": "H",
        "description": "Members of these communities reside mostly in lower-density, rapidly growing suburbs in the South and Midwest. Most householders are between the ages of 35 and 64, and households are mainly comprised of large families with children. Marriage rates are high. Members of this segment are often employed in professional roles and earn middle-tier incomes. Many are self-employed, and some households support their earnings with interest, dividends, or rental properties. Available housing is predominantly composed of single-family units built in the 1990s and 2000s, with home values and rents that mirror national averages. The rate of new development is notably higher here than in most other regions. Many households have multiple vehicles, and long commutes are common.",
        "median_age": 39.0,
        "median_household_income": 111751,
        "median_net_worth": 499190,
        "homeownership_rate": 0.852,
        "bachelors_degree_rate": 0.420,
    },
    "H2": {
        "number": 36,
        "name": "Boomburbs",
        "life_mode": "Suburban Style",
        "life_mode_code": "H",
        "description": "These neighborhoods are primarily located in the suburbs of metropolitan areas with populations exceeding 500,000, mainly in the South and West. Most members of the segment are between 25 and 54, with an overall population that is young; nearly a third are under the age of 18. Married couples with or without children are prevalent in this segment. Household incomes are predominantly upper tier, and workers are frequently employed full time in fields including government, management, sales, business, and finance. They reside in newer single-family homes, typically constructed in 2000 or later. More than half of the homes are valued between $300,000 and $500,000. Nearly a third of households own three or more vehicles.",
        "median_age": 34.5,
        "median_household_income": 131202,
        "median_net_worth": 539415,
        "homeownership_rate": 0.829,
        "bachelors_degree_rate": 0.480,
    },
    "H3": {
        "number": 37,
        "name": "Neighborhood Spirit",
        "life_mode": "Suburban Style",
        "life_mode_code": "H",
        "description": "Residents in these neighborhoods live in the suburbs of large metropolitan areas, with a high concentration in the West, particularly California. The population skews slightly older, with a higher proportion of people aged 45 to 64. Households tend to be large and multigenerational, including adult children living with parents. Residents are often employed in skilled occupations, with notable self-employment and jobs with local government, and may receive income from interest, dividends, and rental properties. Homeownership is prevalent, with most homes valued at $500,000 or higher and occupants living in them for many years. Rental prices are among the highest in the country. Homes are generally older, many built before 1970. Commuting is a significant aspect of life, and many households own multiple vehicles.",
        "median_age": 43.0,
        "median_household_income": 138083,
        "median_net_worth": 764889,
        "homeownership_rate": 0.807,
        "bachelors_degree_rate": 0.450,
    },
    "H4": {
        "number": 38,
        "name": "Urban Chic",
        "life_mode": "Suburban Style",
        "life_mode_code": "H",
        "description": "Residents in this segment live in suburban areas with a notable presence in urban vicinities, mostly near large, coastal metropolitan areas, especially in California, New York, Massachusetts, and Washington. Predominantly composed of married couples, many are raising young children. They are highly educated and hold professional positions in technology, health care, and education sectors, as well as a notable number who are self-employed. Some have additional earnings from interest, dividends, and rental properties. Household incomes generally fall within the upper tier, and many are significantly higher than the national average. They have substantial net worth and retirement savings. About half of housing units are detached single-family homes, and there is also a notable presence of attached single-family homes and apartment complexes. Most households own one or two vehicles.",
        "median_age": 41.9,
        "median_household_income": 144754,
        "median_net_worth": 572986,
        "homeownership_rate": 0.625,
        "bachelors_degree_rate": 0.690,
    },

    # =========================================================================
    # LifeMode I: Rural Rhythms
    # =========================================================================
    "I1": {
        "number": 39,
        "name": "Small Town Sincerity",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "One in four residents in this segment live outside metropolitan areas, often in small towns with a semirural setting. Nearly one-third of the population is 55 or older, and nonfamily and single-parent households are dominant. Residents are primarily employed in manufacturing, food service, production, and retail. Most residents have a high school diploma. More than half of households earn middle-tier incomes; social security and other forms of public assistance provide essential support. Residents own at least one vehicle per household, though many workers walk or bike to nearby employment. Rental costs are among the lowest in the country. Neighborhoods are older, with most homes built before 1990, and are predominantly comprised of single-family units, but duplexes are also common.",
        "median_age": 41.9,
        "median_household_income": 40589,
        "median_net_worth": 45310,
        "homeownership_rate": 0.558,
        "bachelors_degree_rate": 0.150,
    },
    "I2": {
        "number": 40,
        "name": "Scenic Byways",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "Communities in this segment are located outside city boundaries, largely in the South. Population density is low, and the landscape is characterized by expansive open spaces and undeveloped land. Households primarily consist of married or widowed older adults. Many residents are approaching retirement or are retired, having had careers working in skilled trades such as agriculture, manufacturing, mining, construction, and utilities. The health, food, and retail sectors provide essential job opportunities for many, while social security and other forms of public assistance offer additional financial support. Commuting times are long. Homes are predominantly owned, and single-family and manufactured homes are common. Vacancy rates tend to be higher than average, with a notable portion being seasonal units.",
        "median_age": 43.7,
        "median_household_income": 48428,
        "median_net_worth": 138719,
        "homeownership_rate": 0.785,
        "bachelors_degree_rate": 0.160,
    },
    "I3": {
        "number": 41,
        "name": "Heartland Communities",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "Neighborhoods in this segment are primarily found in outlying towns and cities across the Midwest. Nearly half of the population resides in low-density suburbs or small towns outside official metropolitan or micropolitan area boundaries, with a notable portion living in very rural settings. Households are predominantly married couples and single-person households. Residents work in industries such as construction, utilities, health care, and agriculture. The manufacturing industry has historically played a significant role in their lives, often spanning multiple generations. There is an above-average portion of the population supported by social security and other forms of public assistance. Most housing units were built before 1990, with more than half built before 1970. Commutes are generally short, and residents tend to own one or more vehicles.",
        "median_age": 43.6,
        "median_household_income": 60072,
        "median_net_worth": 165309,
        "homeownership_rate": 0.716,
        "bachelors_degree_rate": 0.200,
    },
    "I4": {
        "number": 42,
        "name": "Rooted Rural",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "Heavily concentrated in the South and Appalachia, these residents often live in very rural areas far from job centers and outside towns and cities. Households are predominantly married couples and single-person households. Residents work in industries such as manufacturing, construction, agriculture, mining, and utilities. Employment in health care, retail, accommodation, and food services is also significant in these communities. Labor force participation is lower than average. These stable rural communities are characterized by long-term homeownership. Single-family homes are common, with one in five units being mobile homes. Vacancy rates are higher than the national average. Owning multiple cars is essential, as long commutes (sometimes across county or state lines) are typical.",
        "median_age": 46.9,
        "median_household_income": 61776,
        "median_net_worth": 225364,
        "homeownership_rate": 0.824,
        "bachelors_degree_rate": 0.180,
    },
    "I5": {
        "number": 43,
        "name": "Rural Resort Dwellers",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "Neighborhoods in this segment are distributed throughout the country and are concentrated in resort locations and areas with seasonal recreation. With approximately half of the population aged 55 and over, the senior age dependency rate is high. Nearly half of households are comprised of married couples without children. While most of this segment is rural and remote, some communities are within commuting distance (though often long commutes) of major urban job centers. Residents tend to have skilled jobs in construction and manufacturing. Rates of self-employment and government employment are higher than average, and there is a notable veteran population. There is a high number of second homes used for recreation, with one in three housing units designated for seasonal or occasional use.",
        "median_age": 55.1,
        "median_household_income": 71031,
        "median_net_worth": 321308,
        "homeownership_rate": 0.840,
        "bachelors_degree_rate": 0.280,
    },
    "I6": {
        "number": 44,
        "name": "Southern Satellites",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "These communities, though within metropolitan or micropolitan boundaries, are largely concentrated on the outskirts in suburbs or very low-density areas. The population is generally older, with more than half of household heads aged 55 and above, though younger families with school-aged children are also prevalent. Both child and senior age dependency rates are higher than the national averages. Socioeconomically, this segment mirrors national averages, with most earning middle-tier incomes. For the older population, low-tier incomes are often supported by social security and other forms of public assistance. Residents work in industries such as manufacturing, health care, retail, construction, mining, and agriculture. The cost of living is low, and long commutes of more than 30 minutes, sometimes crossing county or state lines, are common.",
        "median_age": 41.5,
        "median_household_income": 72167,
        "median_net_worth": 254904,
        "homeownership_rate": 0.819,
        "bachelors_degree_rate": 0.220,
    },
    "I7": {
        "number": 45,
        "name": "Country Charm",
        "life_mode": "Rural Rhythms",
        "life_mode_code": "I",
        "description": "These communities are evenly distributed across metropolitan, micropolitan, and nonmetropolitan areas, with the highest concentration in the Midwest. Most residents live outside defined towns or cities in very low-density regions. Agriculture is at the heart of these communities, with many residents self-employed on their own farms or working for neighboring farms. Residents also find employment opportunities in manufacturing, construction, mining, and utilities. Residents tend to be older, with more married couples than singles, however, there is a higher-than-average presence of children under 18. Residents tend to own at least two vehicles.",
        "median_age": 43.6,
        "median_household_income": 78155,
        "median_net_worth": 298064,
        "homeownership_rate": 0.838,
        "bachelors_degree_rate": 0.240,
    },

    # =========================================================================
    # LifeMode J: Golden Years
    # =========================================================================
    "J1": {
        "number": 46,
        "name": "Senior Escapes",
        "life_mode": "Golden Years",
        "life_mode_code": "J",
        "description": "While much of this segment's population is scattered across the U.S., the majority reside in the South and West. Most neighborhoods are suburban, on the outskirts of metropolitan areas, and roughly one-quarter of residents live in rural areas. This segment is growing at approximately twice the national rate, with more than half of householders aged 65 and older. There is a notable population of retired military personnel. The majority of households earn low- to middle-tier incomes, with many supported by social security and other forms of public assistance, and about a third live on retirement income. Many homes remain vacant for much of the year, drawing seasonal residents when colder weather strikes elsewhere. Homeownership rates are high, with manufactured homes making up nearly half of all housing. Most households own one or two cars.",
        "median_age": 61.5,
        "median_household_income": 50282,
        "median_net_worth": 208760,
        "homeownership_rate": 0.790,
        "bachelors_degree_rate": 0.220,
    },
    "J2": {
        "number": 47,
        "name": "The Elders",
        "life_mode": "Golden Years",
        "life_mode_code": "J",
        "description": "Communities in this segment tend to be designed for senior or assisted living and are primarily located in warmer climates with seasonal populations in states such as Florida, Arizona, and California. This is the oldest segment, as the majority of residents are at least 65 years old. Age dependency ratios are more than triple the national average. These elder residents are primarily retired, living off retirement payments, investments, or supported by social security and other forms of public assistance. Population growth in these popular neighborhoods is twice the national rate. Most of the population lives in the suburbs of metropolitan areas, providing close proximity to family and medical facilities. A high prevalence of second homes supports seasonal travel. Most homes are valued above $200,000, and one-third of all housing was built after 2000.",
        "median_age": 74.1,
        "median_household_income": 69169,
        "median_net_worth": 530281,
        "homeownership_rate": 0.856,
        "bachelors_degree_rate": 0.350,
    },
    "J3": {
        "number": 48,
        "name": "Retirement Communities",
        "life_mode": "Golden Years",
        "life_mode_code": "J",
        "description": "These neighborhoods are spread across metropolitan areas, both large and small, nationwide. Most residents have settled in the suburbs. A quarter of the population consists of people aged 75 years and above, and nearly half of households are single individuals. Many households depend on a mix of retirement funds, investment income, and social security and other forms of public assistance, while just over half also earn wages and salaries. Households typically earn middle-tier incomes; accrued net worth tends to be above the national average. Many are active in the workforce, with employment in professional sectors such as education, health care, management, sales, and technology. Most residents live in single-family homes, duplexes, or apartments, and rent exceeds the national average. Additionally, many assisted living and nursing facilities are found in these areas.",
        "median_age": 55.0,
        "median_household_income": 80402,
        "median_net_worth": 263394,
        "homeownership_rate": 0.599,
        "bachelors_degree_rate": 0.400,
    },
    "J4": {
        "number": 49,
        "name": "Silver and Gold",
        "life_mode": "Golden Years",
        "life_mode_code": "J",
        "description": "These low-density neighborhoods are located in suburban, rural, or coastal settings, often in warmer climates. Residents tend to be aged 55 and older, and more than half of households comprise married couples with no children. The median net worth is approximately three times that of the U.S. median. Residents earn incomes in the middle and upper tiers, supported by a blend of retirement funds and social security and other forms of public assistance. Half of workers earn wages and salaries, often in professional roles such as management, health care, technology, and legal fields, and one in five is self-employed. The housing landscape is predominantly made up of single-family units, and a significant portion of homes were built after 2000. This segment ranks among the highest for seasonal vacancies, with around a third of units occasionally vacant. Housing affordability is low compared to the national average.",
        "median_age": 64.4,
        "median_household_income": 102652,
        "median_net_worth": 811588,
        "homeownership_rate": 0.873,
        "bachelors_degree_rate": 0.450,
    },

    # =========================================================================
    # LifeMode K: Comfortable Cornerstone
    # =========================================================================
    "K1": {
        "number": 50,
        "name": "Legacy Hills",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "These neighborhoods are scattered nationwide, with above-average concentrations in the Midwest and South. Residents live in suburbs near metro areas with populations of 500,000 or more. Most residents are aged 45 and above, and a notable portion are either widowed or divorced, contributing to a high number of single-person households and smaller average household sizes. There is also a notable presence of this segment in small and remote towns and micropolitan areas, and many residents, particularly renters, have moved into these neighborhoods more recently. There are a higher-than-average number of workers in social service occupations. Homes are valued between $150,000 and $300,000. Half of the homes are single-family units, many constructed between 1950 and 1990, and the rest are a mix of low-rise and high-rise apartment complexes.",
        "median_age": 45.6,
        "median_household_income": 55927,
        "median_net_worth": 87823,
        "homeownership_rate": 0.494,
        "bachelors_degree_rate": 0.200,
    },
    "K2": {
        "number": 51,
        "name": "Middle Ground",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "Predominantly found in the Midwest, followed by the South, these suburban neighborhoods are especially common in states such as Missouri, Michigan, Nebraska, Ohio, and Wisconsin. These neighborhoods are slightly younger than the U.S. average, and households tend to consist of married couples, cohabiting couples, and single-person households. Labor force participation is high, with many families having two or more workers. Employment tends to be in the manufacturing, health care, and retail sectors, with a higher-than-average presence of skilled trade workers. Housing is more affordable than the national average for both renters and homeowners. A significant percentage of homes are valued between $100,000 and $200,000, and most residences are single-family detached houses built between 1950 and 1990.",
        "median_age": 38.8,
        "median_household_income": 69074,
        "median_net_worth": 168044,
        "homeownership_rate": 0.673,
        "bachelors_degree_rate": 0.260,
    },
    "K3": {
        "number": 52,
        "name": "Loyal Locals",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "Though prevalent nationwide, the highest concentrations of these communities are found in the Midwest and South. While many are in the suburbs of small metropolitan and micropolitan areas, these neighborhoods also have significant concentrations in small and remote towns. Residents are predominantly aged 65 years and above, and many are widowed or married without children living at home. Housing is more affordable than the national average: more than half of the homes in this segment are valued between $150,000 and $300,000. The majority of households consist of single-family homes, primarily built between 1950 and 1990. Commutes are typically short, with most residents driving alone to work, due to limited public transportation options. These neighborhoods generally have low population density and stable growth patterns.",
        "median_age": 46.4,
        "median_household_income": 77226,
        "median_net_worth": 291287,
        "homeownership_rate": 0.782,
        "bachelors_degree_rate": 0.280,
    },
    "K4": {
        "number": 53,
        "name": "Classic Comfort",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "These neighborhoods are typically found in the suburbs of major metropolitan areas, particularly in the South and Midwest, including states such as Michigan, Illinois, and Texas. The median age is slightly above that of the U.S. Most households earn middle-tier incomes, and labor force participation is high; most work full-time jobs, and many families are supported by multiple earners. Employment is mostly in wholesale trade, health care, education, and manufacturing sectors. Affordable housing is prominent, with most homes valued between $150,000 and $300,000 and rental prices below the national average. Homeowners significantly outnumber renters, and many homes were built between 1950 and 2000. Short, solo commutes are common, with households typically owning several vehicles. During the day, the residential population exceeds the working population.",
        "median_age": 40.2,
        "median_household_income": 88893,
        "median_net_worth": 317594,
        "homeownership_rate": 0.805,
        "bachelors_degree_rate": 0.320,
    },
    "K5": {
        "number": 54,
        "name": "Dreambelt",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "These suburban neighborhoods are predominantly located in the West, often outside the principal cities of major metropolitan areas. About half of the population is between 35 and 74, and most households consist of married or cohabiting couples. Most households earn middle-tier incomes, and labor force participation is high. This segment has a high concentration of employment in public administration, construction, health care, and retail trade sectors. Neighborhoods consist mainly of single-family homes built between 1950 and 1990, offering ample parking space, often for three or more vehicles. A significant portion of the population commutes alone by car. Rental rates and home prices are substantial, with more than half of the properties for purchase valued between $300,000 and $500,000.",
        "median_age": 41.5,
        "median_household_income": 94802,
        "median_net_worth": 339974,
        "homeownership_rate": 0.758,
        "bachelors_degree_rate": 0.350,
    },
    "K6": {
        "number": 55,
        "name": "City Greens",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "Most residents in this segment live in metropolitan areas with populations exceeding 500,000. More than half of residents aged 25 and older hold a bachelor's or graduate degree. Married couples are predominant, though a significant proportion of households are nonfamily, including singles, households with no relatives, and cohabiting couples without children. More than half of households have dual incomes, with health care, education, and retail trade being key sectors. Homeownership rates are slightly above the national average, and most homes are valued between $200,000 and $500,000. Even with rents slightly higher than the national average, vacancy rates are relatively low. The housing stock is older, with many homes constructed before 1970. While single-family detached homes are common, there is also a higher-than-average presence of single-family attached units such as row houses, duplexes, and townhomes.",
        "median_age": 41.4,
        "median_household_income": 97516,
        "median_net_worth": 301867,
        "homeownership_rate": 0.659,
        "bachelors_degree_rate": 0.400,
    },
    "K7": {
        "number": 56,
        "name": "Room to Roam",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "These communities are mainly found within metropolitan areas but tend not to be in the mega metropolises. The highest concentrations are found in the Midwest and South. More than half of household heads are aged 55 and older, and one in five individuals are aged 65 and above. Married couples, often without children, form most households, while nonfamily households represent a quarter of the total households. Self-employment is notable, and employment tends to be in manufacturing, health care, and retail. Most housing in this market consists of owner-occupied, single-family homes rather than rentals, with housing built primarily between 1970 and 2000 and generally priced lower than the national average. Owning multiple vehicles is typical, with driving alone as the primary means of commuting.",
        "median_age": 46.2,
        "median_household_income": 99689,
        "median_net_worth": 506754,
        "homeownership_rate": 0.890,
        "bachelors_degree_rate": 0.300,
    },
    "K8": {
        "number": 57,
        "name": "Burbs and Beyond",
        "life_mode": "Comfortable Cornerstone",
        "life_mode_code": "K",
        "description": "The highest concentrations of these communities are in the West, with additional representation in the South and Northeast. Nearly half of the population is aged 55 or above, and most households are composed of married couples without children. Incomes are typically middle- to upper-tier, and more than three-quarters of households receive retirement or are supported by social security and other forms of public assistance. The rate of self-employment is high, with significant employment in professional fields such as management, sales, and health care. More than half of single-family homes in these areas are valued at $500,000 or more, and they are often located in close proximity to nature and outdoor recreation. Seasonal vacancy rates, more than double the average, suggest the presence of second homes, and households typically own multiple vehicles.",
        "median_age": 51.1,
        "median_household_income": 119769,
        "median_net_worth": 779483,
        "homeownership_rate": 0.845,
        "bachelors_degree_rate": 0.420,
    },

    # =========================================================================
    # LifeMode L: Affluent Estates
    # =========================================================================
    "L1": {
        "number": 58,
        "name": "Savvy Suburbanites",
        "life_mode": "Affluent Estates",
        "life_mode_code": "L",
        "description": "These neighborhoods tend to be concentrated in New England and the Mid-Atlantic. Some couples have children who have grown up and left the house, and around a quarter still have kids at home. Residents work in professional fields such as management and finance. The combined wages of both spouses position these families solidly in the middle to upper income tiers. Investments, retirement income, and valuable properties also contribute to the high net worth of households commonly found in these neighborhoods. Residents in this segment gravitate toward suburban communities, which include both newly developed and well-established areas, within major metropolitan areas. Nearly all homes are single-family and owner-occupied, with very few rental properties available, and most homes were built between 1970 and 2000.",
        "median_age": 44.0,
        "median_household_income": 139696,
        "median_net_worth": 915346,
        "homeownership_rate": 0.909,
        "bachelors_degree_rate": 0.580,
    },
    "L2": {
        "number": 59,
        "name": "Professional Pride",
        "life_mode": "Affluent Estates",
        "life_mode_code": "L",
        "description": "While these neighborhoods can be found nationwide, they are most prevalent in the South and West. Over three-quarters of all residents are married, and many households have multiple children enrolled in K-12 schools. Over half of residents hold bachelor's or graduate degrees, and they tend to be employed in technology, engineering, and management roles. A significant portion of these individuals choose to work from home. Households tend to have dual incomes, and many individuals earn some of the highest salaries in the nation. Residents typically live in communities featuring newly constructed, owner-occupied single-family homes in the expanding outer suburbs and exurbs of major metropolitan areas. Many homeowners have a mortgage due to new construction costs.",
        "median_age": 38.6,
        "median_household_income": 187750,
        "median_net_worth": 1178630,
        "homeownership_rate": 0.894,
        "bachelors_degree_rate": 0.650,
    },
    "L3": {
        "number": 60,
        "name": "Top Tier",
        "life_mode": "Affluent Estates",
        "life_mode_code": "L",
        "description": "The concentration of neighborhoods in this segment is particularly high in New England, the Mid-Atlantic, and the Pacific. Residents of this segment reside in suburban neighborhoods within the largest metropolitan areas. Nearly half of householders are between the ages of 45 and 64, and households are primarily married couples with or without children living at home. Many families send their children to private K-12 schools. Approximately three-quarters of residents hold undergraduate or graduate degrees, and they typically hold positions as executives, professionals, or business owners. A growing number of workers in this segment work from home. This segment has the highest net worth among all segments. Neighborhoods are almost exclusively composed of single-family homes.",
        "median_age": 45.4,
        "median_household_income": 209720,
        "median_net_worth": 1734059,
        "homeownership_rate": 0.903,
        "bachelors_degree_rate": 0.720,
    },
}


# =============================================================================
# API Functions
# =============================================================================

class GeocodingResult(BaseModel):
    """Result from geocoding a location."""
    address: str
    location: dict  # {"x": longitude, "y": latitude}
    score: float
    attributes: dict = {}


async def get_esri_client() -> httpx.AsyncClient:
    """Create an async HTTP client for Esri API calls."""
    return httpx.AsyncClient(
        timeout=30.0,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def geocode_location(
    query: str,
    max_results: int = 5,
) -> list[GeocodingResult]:
    """
    Geocode a location query using ArcGIS Geocoding service.

    Args:
        query: Location search string (e.g., "Dallas, TX" or "Dallas")
        max_results: Maximum number of results to return

    Returns:
        List of GeocodingResult with matching locations (deduplicated)
    """
    api_key = settings.effective_arcgis_api_key
    if not api_key:
        print("No ArcGIS API key available for geocoding")
        return []

    params = {
        "f": "json",
        "token": api_key,
        "singleLine": query,
        "maxLocations": max_results * 2,  # Get more to filter duplicates
        "outFields": "PlaceName,Place_addr,City,Region,Country,Type",
    }

    async with await get_esri_client() as client:
        try:
            response = await client.get(
                "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",
                params=params
            )
            response.raise_for_status()
            data = response.json()

            results = []
            seen_addresses = set()
            seen_coords = set()

            for candidate in data.get("candidates", []):
                address = candidate.get("address", "")
                location = candidate.get("location", {})

                # Create a coordinate key (rounded to avoid near-duplicates)
                coord_key = (
                    round(location.get("x", 0), 2),
                    round(location.get("y", 0), 2)
                )

                # Skip if we've seen this exact address or very close coordinates
                if address in seen_addresses or coord_key in seen_coords:
                    continue

                seen_addresses.add(address)
                seen_coords.add(coord_key)

                results.append(GeocodingResult(
                    address=address,
                    location=location,
                    score=candidate.get("score", 0),
                    attributes=candidate.get("attributes", {}),
                ))

                # Stop once we have enough unique results
                if len(results) >= max_results:
                    break

            return results

        except httpx.HTTPError as e:
            print(f"Geocoding error: {e}")
            return []


async def enrich_location(
    latitude: float,
    longitude: float,
    buffer_miles: float = 1.0,
) -> EnrichmentResult | None:
    """
    Enrich a location with tapestry and demographic data from Esri.

    Args:
        latitude: Location latitude
        longitude: Location longitude
        buffer_miles: Radius around point (default 1 mile)

    Returns:
        EnrichmentResult with segment and demographic data, or None if failed
    """
    if not settings.arcgis_api_key:
        return None

    # Check cache
    cache_key = f"{latitude:.4f},{longitude:.4f},{buffer_miles}"
    if cache_key in _enrichment_cache:
        cached_data, cached_time = _enrichment_cache[cache_key]
        if datetime.now() - cached_time < timedelta(hours=settings.esri_cache_ttl_hours):
            return EnrichmentResult(**cached_data)

    study_areas = json.dumps([{
        "geometry": {"x": longitude, "y": latitude},
        "areaType": "RingBuffer",
        "bufferUnits": "esriMiles",
        "bufferRadii": [buffer_miles]
    }])

    params = {
        "f": "json",
        "token": settings.arcgis_api_key,
        "studyAreas": study_areas,
        "dataCollections": json.dumps(["tapestry", "KeyUSFacts"]),
        "useData": json.dumps({"sourceCountry": "US"}),
        "returnGeometry": "false",
    }

    async with await get_esri_client() as client:
        try:
            response = await client.post(
                f"{settings.esri_geoenrich_base_url}/Enrich",
                data=params
            )
            response.raise_for_status()
            data = response.json()

            result = _parse_enrich_response(data)
            if result:
                _enrichment_cache[cache_key] = (result.model_dump(), datetime.now())
            return result

        except httpx.HTTPError as e:
            print(f"Esri API error: {e}")
            return None


def _parse_enrich_response(data: dict) -> EnrichmentResult | None:
    """Parse Esri GeoEnrichment response into structured result."""
    try:
        results = data.get("results", [])
        if not results:
            return None

        feature_set = results[0].get("value", {}).get("FeatureSet", [])
        if not feature_set:
            return None

        features = feature_set[0].get("features", [])
        if not features:
            return None

        attrs = features[0].get("attributes", {})

        return EnrichmentResult(
            dominant_segment_code=attrs.get("TSEGCODE", ""),
            dominant_segment_name=attrs.get("TSEGNAME", ""),
            total_population=attrs.get("TOTPOP"),
            total_households=attrs.get("TOTHH"),
            median_age=attrs.get("MEDAGE"),
        )
    except Exception as e:
        print(f"Error parsing Esri response: {e}")
        return None


def get_segment_profile(segment_code: str) -> SegmentProfile | None:
    """
    Get detailed profile for a tapestry segment from static data.

    Args:
        segment_code: Segment code like "A1", "A2", "B1", etc.

    Returns:
        SegmentProfile with all details, or None if not found
    """
    code = segment_code.upper().strip()
    if code in SEGMENT_PROFILES:
        return SegmentProfile(code=code, **SEGMENT_PROFILES[code])
    return None


def get_segment_profiles(segment_codes: list[str]) -> dict[str, SegmentProfile]:
    """
    Get detailed profiles for multiple tapestry segments.

    Args:
        segment_codes: List of segment codes

    Returns:
        Dict mapping code to SegmentProfile
    """
    profiles = {}
    for code in segment_codes:
        profile = get_segment_profile(code)
        if profile:
            profiles[code.upper()] = profile
    return profiles


def get_all_segment_codes() -> list[str]:
    """Get list of all available segment codes."""
    return list(SEGMENT_PROFILES.keys())


def get_segments_by_lifemode(life_mode_code: str) -> list[SegmentProfile]:
    """Get all segments in a LifeMode group."""
    return [
        SegmentProfile(code=code, **data)
        for code, data in SEGMENT_PROFILES.items()
        if data["life_mode_code"] == life_mode_code.upper()
    ]


def get_segment_context_for_ai(segment_codes: list[str]) -> str:
    """
    Generate formatted context about segments for AI consumption.

    Args:
        segment_codes: List of segment codes to include

    Returns:
        Formatted markdown text with segment information
    """
    profiles = get_segment_profiles(segment_codes)

    if not profiles:
        return ""

    context_parts = []
    for code, profile in profiles.items():
        income_str = f"${profile.median_household_income:,.0f}" if profile.median_household_income else "N/A"
        net_worth_str = f"${profile.median_net_worth:,.0f}" if profile.median_net_worth else "N/A"
        homeowner_str = f"{profile.homeownership_rate * 100:.1f}%" if profile.homeownership_rate else "N/A"

        context_parts.append(f"""### Tapestry Segment {code}: {profile.name}

**LifeMode Group:** {profile.life_mode}

{profile.description}

**Key Demographics (Esri 2025):**
- Median Age: {profile.median_age}
- Median Household Income: {income_str}
- Median Net Worth: {net_worth_str}
- Homeownership Rate: {homeowner_str}""")

    return "\n\n".join(context_parts)


def search_segments_by_name(query: str, limit: int = 5) -> list[SegmentProfile]:
    """
    Search segments by name or description.

    Args:
        query: Search term
        limit: Maximum results to return

    Returns:
        List of matching SegmentProfiles
    """
    query_lower = query.lower()
    matches = []

    for code, data in SEGMENT_PROFILES.items():
        score = 0
        if query_lower in data["name"].lower():
            score += 3
        if query_lower in data["life_mode"].lower():
            score += 2
        if query_lower in data["description"].lower():
            score += 1

        if score > 0:
            matches.append((score, code, data))

    matches.sort(key=lambda x: x[0], reverse=True)
    return [
        SegmentProfile(code=code, **data)
        for _, code, data in matches[:limit]
    ]
