# from app.models.courses import Course, Lesson, Topic
# # from server.app import db
# # from app import db

# # -----------------------------
# # Normalize text (fix encoding issues)
# # -----------------------------
# def normalize_text(text):
#     if not text:
#         return text
#     return (
#         text.replace("’", "'")
#             .replace("ÔÇÖ", "'")
#             .replace("â€™", "'")
#     )


# -----------------------------
# Data 
# -----------------------------
# course_data = {
#     "title": "Programming Fundamentals",
#     "lessons": [
#         {
#             "title": "Introduction to programming",
#             "topics": [
#                 "Problem solving test",
#                 "Programs",
#                 "Summary"
#             ]
#         },
#         {
#             "title": "Storage",
#             "topics": [
#                 "Introduction to Storage",
#                 "Asking the computer to remember",
#                 "Variables",
#                 "Changing values",
#                 "Using variables",
#                 "Storing Text",
#                 "Lists",
#                 "Summary"
#             ]
#         },
#         {
#             "title": "Repeating things",
#             "topics": [
#                 "Introduction to Repeating Things",
#                 "Where to use repeat?",
#                 "Loops",
#                 "While Loop",
#                 "Summary"
#             ]
#         },
#         {
#             "title": "Making decisions",
#             "topics": [
#                 "Introduction to Making Decisions",
#                 "Using If..Then..Else",
#                 "Using Else If",
#                 "Summary"
#             ]
#         },
#         {
#             "title": "Creating lists",
#             "topics": [
#                 "How to store multiple values",
#                 "Summary"
#             ]
#         },
#         {
#             "title": "Grouping instructions",
#             "topics": [
#                 "Similar instructions",
#                 "Create group of instructions",
#                 "Procedures & Functions",
#                 "Let's revise"
#             ]
#         },
#         {
#             "title": "Avoiding mistakes",
#             "topics": [
#                 "What are mistakes?",
#                 "What is debugging?",
#                 "Logic bug",
#                 "Avoiding bug",
#                 "Summary"
#             ]
#         },
#         {
#             "title": "Using computer language",
#             "topics": [
#                 "What is a computer language?",
#                 "Converting code to 0s and 1s",
#                 "Understanding code",
#                 "Let’s revise"
#             ]
#         }
#     ]
# }

# course_data = {
#     "title": "Python For Artificial Intelligence",
#     "lessons": [
#         {
#             "title": "The Robot has Arrived",
#             "topics": [
#                 "Let’s meet Mr. Robot",
#                 "The intelligence of AI",
#                 "Cool applications and features of AI",
#                 "Recap"
#             ]
#         },
#         {
#             "title": "AI works with Python",
#             "topics": [
#                 "Why is Python best for AI?",
#                 "Installing Python",
#                 "Ready for a quiz?"
#             ]
#         },
#         {
#             "title": "Making Mr. Robot think like humans",
#             "topics": [
#                 "How is Machine learning related to AI?",
#                 "Algorithms in Machine learning",
#                 "Recap"
#             ]
#         },
#         {
#             "title": "Classification and Regression using Supervised Learning",
#             "topics": [
#                 "Getting to know Classification",
#                 "The powerful algorithm for classification: Naive Bayes",
#                 "What is Regression?",
#                 "Test yourself"
#             ]
#         },
#         {
#             "title": "The Unsupervised Learning technique: Clustering",
#             "topics": [
#                 "Clusters: What are they?",
#                 "Algorithms for Clustering the Data",
#                 "Let’s revise"
#             ]
#         },
#         {
#             "title": "Getting familiar with Natural Language Processing (NLP)",
#             "topics": [
#                 "Introduction to NLP",
#                 "Terminologies In NLP",
#                 "Quiz session"
#             ]
#         },
#         {
#             "title": "A Python package: NLTK",
#             "topics": [
#                 "Understanding and installation of Natural Language Toolkit (NLTK)",
#                 "Concept of Tokenization, Stemming, and Lemmatization",
#                 "The text modelling: Bag of Words (BoW)",
#                 "A quick test"
#             ]
#         },
#         {
#             "title": "Let’s talk about Deep Learning",
#             "topics": [
#                 "What are Convolutional Neural Networks (CNN)?",
#                 "Getting Familiar with ANN and Perceptron",
#                 "Let’s revise"
#             ]
#         }
#     ]
# }


# # -----------------------------
# # Seeder
# # -----------------------------
# def seed():
#     # Normalize course title
#     course_title = normalize_text(course_data["title"])

#     # Get or create course
#     course = Course.query.filter_by(title=course_title).first()
#     if not course:
#         course = Course(title=course_title)
#         db.session.add(course)
#         db.session.flush()

#     # Loop lessons
#     for lesson_index, lesson_data in enumerate(course_data["lessons"]):
#         lesson_title = normalize_text(lesson_data["title"])

#         lesson = Lesson.query.filter_by(
#             title=lesson_title,
#             course_id=course.id
#         ).first()

#         if not lesson:
#             lesson = Lesson(
#                 title=lesson_title,
#                 course_id=course.id,
#                 order=lesson_index  # optional (if column exists)
#             )
#             db.session.add(lesson)
#             db.session.flush()

#         # Loop topics
#         for topic_index, topic_title in enumerate(lesson_data["topics"]):
#             topic_title = normalize_text(topic_title)

#             exists = Topic.query.filter_by(
#                 title=topic_title,
#                 lesson_id=lesson.id
#             ).first()

#             if not exists:
#                 topic = Topic(
#                     title=topic_title,
#                     lesson_id=lesson.id,
#                     order=topic_index  # optional (if column exists)
#                 )
#                 db.session.add(topic)

#     db.session.commit()
#     print("✅ Fundamentals course seeded successfully.")


# # -----------------------------
# # Run مباشرة
# # -----------------------------
# if __name__ == "__main__":
#     seed()



""" 
for description:

Generate 2 convincing professional course descriptions simplified and convincing based on contexts, 
brief and extended versions.

for lessons:

following this format, arrange this lesson/topics consistently: course_data={"title": "Android Development", "lessons": [{ "title": "How It All Began", "topics": [ "Android Is Born", "The Sweet Journey", "Quick Review-1"]}, {

"""
# v2
from sqlalchemy.orm import Session
# from app.db.session import SessionLocal  # adjust if your path differs

from app.models import Course, Lesson, Topic
from app.db.database_0 import SessionLocal
# from app.db.database import SessionLocal


# -----------------------------
# Normalize text
# -----------------------------
def normalize_text(text):
    if not text:
        return text
    return (
        text.replace("’", "'")
            .replace("ÔÇÖ", "'")
            .replace("â€™", "'")
    )


# -----------------------------
# Data
# -----------------------------
course_data_python4AI = {
    "title": "Python For Artificial Intelligence",
    "lessons": [
        {
            "title": "The Robot has Arrived",
            "topics": [
                "Let’s meet Mr. Robot",
                "The intelligence of AI",
                "Cool applications and features of AI",
                "Recap"
            ]
        },
        {
            "title": "AI works with Python",
            "topics": [
                "Why is Python best for AI?",
                "Installing Python",
                "Ready for a quiz?"
            ]
        },
        {
            "title": "Making Mr. Robot think like humans",
            "topics": [
                "How is Machine learning related to AI?",
                "Algorithms in Machine learning",
                "Recap"
            ]
        },
        {
            "title": "Classification and Regression using Supervised Learning",
            "topics": [
                "Getting to know Classification",
                "The powerful algorithm for classification: Naive Bayes",
                "What is Regression?",
                "Test yourself"
            ]
        },
        {
            "title": "The Unsupervised Learning technique: Clustering",
            "topics": [
                "Clusters: What are they?",
                "Algorithms for Clustering the Data",
                "Let’s revise"
            ]
        },
        {
            "title": "Getting familiar with Natural Language Processing (NLP)",
            "topics": [
                "Introduction to NLP",
                "Terminologies In NLP",
                "Quiz session"
            ]
        },
        {
            "title": "A Python package: NLTK",
            "topics": [
                "Understanding and installation of Natural Language Toolkit (NLTK)",
                "Concept of Tokenization, Stemming, and Lemmatization",
                "The text modelling: Bag of Words (BoW)",
                "A quick test"
            ]
        },
        {
            "title": "Let’s talk about Deep Learning",
            "topics": [
                "What are Convolutional Neural Networks (CNN)?",
                "Getting Familiar with ANN and Perceptron",
                "Let’s revise"
            ]
        }
    ]
}

course_data_ML = {
    "title": "Introduction to Machine Learning",
    "lessons": [
        {
            "title": "Introduction",
            "topics": [
                "ML and AI",
                "Let’s revise"
            ]
        },
        {
            "title": "How does it work?",
            "topics": [
                "Teaching to machines",
                "Patterns, patterns, patterns",
                "Let’s revise"
            ]
        },
        {
            "title": "Useful or not?",
            "topics": [
                "Everything by hand",
                "Modern world and Big Data",
                "Let’s revise"
            ]
        },
        {
            "title": "Simple applications",
            "topics": [
                "Manual approach",
                "ML approach",
                "Let’s revise"
            ]
        },
        {
            "title": "Back in time",
            "topics": [
                "Baby steps",
                "The Artificial Intelligence winter",
                "New discoveries",
                "Let’s revise"
            ]
        },
        {
            "title": "The working details",
            "topics": [
                "ML in detail",
                "Discovering features",
                "Black box",
                "Let’s revise"
            ]
        },
        {
            "title": "Approaches",
            "topics": [
                "Choosing with trees",
                "Regression",
                "Clustering",
                "Let’s revise"
            ]
        },
        {
            "title": "The real deal",
            "topics": [
                "Deep Learning",
                "Neural Networks",
                "Let’s revise"
            ]
        },
        {
            "title": "Ethics in ML",
            "topics": [
                "Good vs bad",
                "Can ML be evil?",
                "Let’s revise"
            ]
        },
        {
            "title": "The future of ML",
            "topics": [
                "ML on mobile",
                "Results, right now!",
                "Quantum computing"
            ]
        }
    ]
}

course_data_Flask = {
    "title": "Python Flask Framework",
    "lessons": [
        {
            "title": "Introduction to Flask",
            "topics": [
                "Frameworks - What are they?",
                "Getting started with flask",
                "Recap"
            ]
        },
        {
            "title": "Critical Elements",
            "topics": [
                "Jinja & Werkzeug",
                "Werkzeug WSGI toolkit",
                "Recap"
            ]
        },
        {
            "title": "Installation & Working",
            "topics": [
                "Let's Install Flask",
                "Understanding the working of Flask",
                "Recap",
                "PRO"
            ]
        },
        {
            "title": "Create Your Own Application",
            "topics": [
                "Running a Application on server",
                "Basic Terminologies",
                "Recap"
            ]
        },
        {
            "title": "In Depth Features of Flask",
            "topics": [
                "URL Builder",
                "Template in Flask",
                "Recap"
            ]
        },
        {
            "title": "What can Flask do?",
            "topics": [
                "Login System in Flask",
                "Security Aspects",
                "Recap"
            ]
        },
        {
            "title": "Blueprint in Flask",
            "topics": [
                "What is Blueprint?",
                "Blueprint in your Flask App Structure",
                "Recap"
            ]
        },
        {
            "title": "Error Handling",
            "topics": [
                "Redirect and Error",
                "How it works?",
                "Recap"
            ]
        }
    ]
}

course_data_AI_Tools_Mastery = {
  "title": "AI Tools Mastery For Productivity",
  "lessons": [
    {
      "title": "How AI Can Boost Your Productivity?",
      "topics": [
        "Unmasking the Hype",
        "Recap"
      ]
    },
    {
      "title": "Meet Bardeen",
      "topics": [
        "Introduction and Setting Up Bardeen",
        "Let’s Explore Bardeen",
        "Working with Bardeen",
        "Recap"
      ]
    },
    {
      "title": "AI Plugins to Boost Your Productivity",
      "topics": [
        "Exploring ChatGPT Plugins",
        "All About WebPilot",
        "Let's Revise PRO"
      ]
    },
    {
      "title": "AI Tools You Should Know",
      "topics": [
        "Introduction to Smart Slides",
        "The Powerful Link Reader",
        "Recap"
      ]
    },
    {
      "title": "Exploring Advanced AI Tools",
      "topics": [
        "What is VoxScript?",
        "Meet Zapier",
        "Let's Revise"
      ]
    },
    {
      "title": "Tools for Content Creation",
      "topics": [
        "Brainstorming and Ideation with AI",
        "AI-powered Writing Tools",
        "Recap"
      ]
    },
    {
      "title": "AI for Project Management",
      "topics": [
        "Utilizing AI for Risk Assessment",
        "Data-driven Decision Making",
        "Let's Revise"
      ]
    }
  ]
}

course_data_Cryptography={
    "title":"Cryptography",
    "lessons": [
    {
      "title": "Origin of Cryptography",
      "topics": [
        "Roots of Secret Communication",
        "Introduction to Cryptography",
        "Common Terminologies",
        "Let's review"
      ]
    },
    {
      "title": "Modern Cryptography",
      "topics": [
        "Classic Cryptography",
        "Modern Cryptography",
        "Let’s revise"
      ]
    },
    {
      "title": "Traditional Ciphers",
      "topics": [
        "Caeser Cipher",
        "Substitution Cipher",
        "Let’s revise",
        "PRO",
        "The Codebreakers",
        "Cryptanalysis",
        "Frequency Analysis",
        "Let’s revise"
      ]
    },
    {
      "title": "Polyalphabetic Ciphers",
      "topics": [
        "Types of Cipher",
        "Vigenere Square Cipher",
        "Transposition Cipher",
        "Let’s revise"
      ]
    },
    {
      "title": "Explaining 'Enigma'",
      "topics": [
        "Need for Mechanization",
        "Unravelling Enigma",
        "Scrambler Arrangement",
        "Let’s revise"
      ]
    },
    {
      "title": "Modern Ciphers",
      "topics": [
        "Age of Modern Ciphers",
        "Types of Modern Ciphers",
        "Let’s revise"
      ]
    },
    {
      "title": "Public Key Cryptography",
      "topics": [
        "Need for Public Key Cryptography",
        "Procedure of Public Key Cryptography",
        "Let’s revise"
      ]
    },
    {
      "title": "Benefits of Modern Cryptography",
      "topics": [
        "More threats to Data",
        "Data Integrity Checks",
        "Message Authentication Checks",
        "Let’s revise"
      ]
    }
]

}

course_data_Android_Development={
    
    "title": "Android Development",
    
    "lessons": [
        {
            "title": "How It All Began",
            "topics": [
                "Android Is Born",
                "The Sweet Journey",
                "Quick Review-1"
            ]
        },
        {
            "title": "Why Is It Still Exciting?",
            "topics": [
                "Why Is It Still Exciting?",
                "Why Not?",
                "Gear Up",
                "What You Might Already Know",
                "Quick Review-2"
            ]
        },
        {
            "title": "Assembling Your Harness",
            "topics": [
                "Key Components",
                "The Linux Kernel",
                "Quick Review",
                "Libraries",
                "The Application Framework",
                "Android Runtime",
                "Applications",
                "Let’s Revise"
            ]
        },
        {
            "title": "Polishing Your Jewels",
            "topics": [
                "Readying the Machine",
                "Readying Your Dev Tools",
                "Installing and Readying Java JDK",
                "Installing and Readying Android Studio",
                "Installing and Readying Android Studio on Mac & Linux",
                "Let’s Revise"
            ]
        },
        {
            "title": "Kickstart Your First Project",
            "topics": [
                "Your First App",
                "Running the Emulator",
                "Android Studio Anatomy",
                "Let’s Revise"
            ]
        },
        {
            "title": "Dive in Android Development",
            "topics": [
                "Understanding Key Concepts",
                "Fragments",
                "Understanding Intents and Filters in Android",
                "Your Second App",
                "Launching Icons in Android",
                "Running Your Application",
                "Debugging and Version Control",
                "Let’s Revise"
            ]
        },
        {
            "title": "Making Apps Faster and Better",
            "topics": [
                "Advanced Android Concepts",
                "Your Third App",
                "Designing User Interface",
                "Adding Click Listener",
                "Localization In Android",
                "Support Libraries",
                "Let’s Revise"
            ]
        },
        {
            "title": "Preserving Data in Apps",
            "topics": [
                "App Users Need Data",
                "Local Caching and Cookies",
                "Shared Preferences",
                "Local Storage",
                "SQLite Database",
                "Synchronization",
                "App Based on Database",
                "Let's Revise"
            ]
        },
        {
            "title": "Publishing Your Android Application",
            "topics": [
                "Introduction",
                "Building an APK",
                "Creating a Developer Profile",
                "Picking a Price for Your App",
                "Marketing Your App",
                "Uploading Your App",
                "Managing Distribution",
                "Monitoring Downloads",
                "Let's Revise"
            ]
        },
        {
            "title": "Final Review",
            "topics": [
                "Let's take a recap"
            ]
        }
    ]
}

course_data_Software_engineering={

  "title": "Software Engineering",
  
  "lessons": [
    {
      "title": "Software Engineering and its Evolution",
      "topics": [
        "Need of software and its Characteristics",
        "Let's Revise"
      ]
    },
    {
      "title": "Software Development Life Cycle",
      "topics": [
        "What is SDLC?",
        "Let's Revise"
      ]
    },
    {
      "title": "SDLC Models",
      "topics": [
        "WaterFall Model",
        "Prototyping Model",
        "Spiral and Concurrent Model",
        "Let's Revise",
        "PRO"
      ]
    },
    {
      "title": "Software Requirement Specifications (SRS)",
      "topics": [
        "Understanding Requirement Engineering Process",
        "Characteristics of Software Requirements",
        "Let's Revise"
      ]
    },
    {
      "title": "Viewing Software Designs",
      "topics": [
        "Introduction to Software Design",
        "Low-Level Design",
        "Cohesion and Coupling",
        "Let's Revise"
      ]
    },
    {
      "title": "More on Design Plans",
      "topics": [
        "Planning Software Designs",
        "Function Oriented Design",
        "Object-Oriented Design",
        "Software Design Approaches",
        "Let's Revise"
      ]
    },
    {
      "title": "Software Testing",
      "topics": [
        "Testing Objectives",
        "Testing Approaches",
        "Testing Levels",
        "Testing Documentation",
        "Let's Revise"
      ]
    }
  ]
}

course_data_Big_Data_Analytics={
"title": "Big Data Analytics",
  "lessons": [
    {
      "title": "Introduction to Big Data",
      "topics": [
        "What is Big Data?",
        "Real Application of Big data",
        "Let's Revise"
      ]
    },
    {
      "title": "Characteristics and challenges in big data",
      "topics": [
        "Characteristics in Big Data",
        "Challenges in Big data",
        "Let's Revise"
      ]
    },
    {
      "title": "Big data Analytics and its Types",
      "topics": [
        "Why Big data analytics?",
        "Types of Big Data Analytics",
        "Let's Revise"
      ]
    },
    {
      "title": "Big Data Analytics Lifecycle",
      "topics": [
        "Roles of keynote holders",
        "Phases of Lifecycle",
        "Let’s Revise"
      ]
    },
    {
      "title": "Diving deeper into data",
      "topics": [
        "Big data sources",
        "Storage Dilemma",
        "Lets Revise"
      ]
    },
    {
      "title": "Hadoop Overview",
      "topics": [
        "Introduction to Hadoop",
        "Hadoop - HDFS Operations",
        "Lets Revise"
      ]
    },
    {
      "title": "Data Analytics, Big Data and Data Science",
      "topics": [
        "Stating differences",
        "Let's Revise"
      ]
    },
    {
      "title": "Looking back",
      "topics": [
        "How Data can affect IT",
        "Let's Revise"
      ]
    }
  ]
}

course_data_SQL = {
  "title": "SQL",
  "lessons": [
    {
      "title": "The World Of Database",
      "topics": [
        "Introduction to DBMS",
        "Entity Relationship Diagram",
        "Let’s Revise",
      ]},
    
    {
       "title": "Working with Databases",
      "topics":[
        "Understanding ER",
        "Some Database Terminologies",
        "Summary"
      ]
    },
    
    {
      "title": "Introduction to Tables",
      "topics": [
        "What Are Tables?",
        "Working with Tables",
        "Let’s Revise"
      ]
    },
    {
      "title": "Keys in SQL",
      "topics": [
        "Need for Keys",
        "Key Types in SQL",
        "Let’s Revise"
      ]
    },
    {
      "title": "Applications of SQL",
      "topics": [
        "Real-time Applications",
        "The Power of SQL",
        "Recap"
      ]
    },
    {
      "title": "Queries in SQL",
      "topics": [
        "Introduction to Queries",
        "More on Queries",
        "Let’s Revise"
      ]
    },
    {
      "title": "SQL Statements",
      "topics": [
        "Basic SQL Syntax",
        "Working with Sub-Queries",
        "Recap"
      ]
    },
    {
      "title": "Clauses and Views in SQL",
      "topics": [
        "Clauses and Views",
        "Working with Clauses and Views",
        "Let’s Revise"
      ]
    },
    {
      "title": "SQL Constraints",
      "topics": [
        "Working with Constraints",
        "More on Constraints",
        "Recap"
      ]
    },
    {
      "title": "Operators in SQL",
      "topics": [
        "What are Operators?",
        "More on Operators",
        "Let’s Revise"
      ]
    },
    {
      "title": "Core SQL Concepts",
      "topics": [
        "Triggers and JOINS",
        "SQL Injection",
        "Recap"
      ]
    },
    {
      "title": "To Conclude",
      "topics": [
        "Wrapping it up",
        "The Assessment",
        "Final Round-up"
      ]
    }
  ]
}

course_data_PostgreSQL = {
"title": "PostgreSQL",
"lessons": [
{
"title": "Introduction to PostgreSQL",
"topics": [
"What is PostgreSQL?",
"More on PostgreSQL",
"Recap"
]
},
{
"title": "How to install PostgreSQL",
"topics": [
"Installing PostgreSQL",
"Connecting to Database Server",
"Recap"
]
},
{
"title": "All about Database",
"topics": [
"Creating PostgreSQL Database",
"Selecting PostgreSQL Database",
"Dropping a Database",
"Let’s Revise"
]
},
{
"title": "Data Types in PostgreSQL",
"topics": [
"Boolean & Character Data type",
"Numeric Data type",
"Date & Time Data type",
"Let’s Revise"
]
},
{
"title": "Structuring Table",
"topics": [
"How to Create a table?",
"Creating your first table in PostgreSQL",
"Recap"
]
},
{
"title": "PostgreSQL Queries",
"topics": [
"Inserting Data",
"Fetching Data",
"Quiz Time"
]
},
{
"title": "Some PostgreSQL Clauses",
"topics": [
"Where Clause",
"AND & OR Clauses",
"Order By Clause",
"Let’s Revise"
]
},
{
"title": "More on Queries",
"topics": [
"Modifying the table",
"Delete Query",
"Let’s Revise"
]
},
{
"title": "PostgreSQL Alter table",
"topics": [
"What is Alter table?",
"Implementing Alter table commands",
"Let’s Revise"
]
}
]
}

course_data_RDBMS={
  "title": "RDBMS",
  "lessons": [
    {
      "title": "Introduction to RDBMS",
      "topics": [
        "Introduction to RDBMS",
        "History of RDBMS",
        "Let’s Revise"
      ]
    },
    {
      "title": "Advantages and Features of RDBMS",
      "topics": [
        "Advantages of RDBMS",
        "How does RDBMS make our life easy?",
        "Some important features of RDBMS",
        "Let’s Revise"
      ]
    },
    {
      "title": "ER Model",
      "topics": [
        "Introduction to ER-Model",
        "Components of ER Model",
        "Let’s Revise"
      ]
    },
    {
      "title": "Attributes in ER Model",
      "topics": [
        "More about Attributes",
        "Let’s Revise",
        "Types of Attributes"
      ]
    },
    {
      "title": "Relations in ER Model",
      "topics": [
        "More about Relations",
        "Degree of Relations",
        "Types of Relations",
        "Let’s Revise"
      ]
    },
    {
      "title": "Tables in RDBMS",
      "topics": [
        "Introduction to Tables",
        "Terms Related to Tables",
        "Let’s Revise"
      ]
    },
    {
      "title": "Keys in RDBMS",
      "topics": [
        "Need for keys in RDBMS",
        "Types of Keys in RDBMS",
        "Let’s Revise"
      ]
    },
    {
      "title": "Normalization of Tables",
      "topics": [
        "Introduction to Normalization",
        "Types of Normalization",
        "Let’s Revise"
      ]
    },
    {
      "title": "Codd’s Rule for RDBMS",
      "topics": [
        "Codd’s Rules",
        "Let’s Revise"
      ]
    }
  ]
}

course_data_MongoDB={
  "title": "MongoDB",
  "lessons": [
    {
      "title": "Introduction to MongoDB",
      "topics": [
        "What is MongoDB?",
        "Why and Where is MongoDB Used?",
        "Let’s Revise"
      ]
    },
    {
      "title": "What is NoSQL?",
      "topics": [
        "Data and database Management System",
        "Different Database Management Systems",
        "NoSQL… Not Only SQL!",
        "Let’s Revise"
      ]
    },
    {
      "title": "Let’s see how to install MongoDB",
      "topics": [
        "What you will need?",
        "Launch MongoDB",
        "Let’s Revise",
        "PRO"
      ]
    },
    {
      "title": "Database through Documents and Collections in MongoDB",
      "topics": [
        "Difference between Database Collections and Documents in MongoDB",
        "Document in MongoDB",
        "Collection in MongoDB",
        "Let’s Revise"
      ]
    },
    {
      "title": "JSON and BSON! The difference",
      "topics": [
        "What is JSON?",
        "What is BSON?",
        "Let’s Revise"
      ]
    },
    {
      "title": "Time to Create and Drop databases and collections!",
      "topics": [
        "How to create a database in MongoDB?",
        "How to drop a database in MongoDB?",
        "Creating a collection",
        "Creating a collection automatically the MongoDB way!",
        "Dropping a collection from MongoDB",
        "Let’s Revise"
      ]
    },
    {
      "title": "Time for some CURD!",
      "topics": [
        "Insert Document",
        "Update Document",
        "Delete documents",
        "Query documents in MongoDB",
        "Let’s Revise"
      ]
    },
    {
      "title": "Data types in MongoDB",
      "topics": [
        "Different data types supported in MongoDB",
        "String and Numbers in MongoDB",
        "Date and Array data types in MongoDB",
        "Boolean and ObjectId data types in MongoDB",
        "Let’s Revise"
      ]
    },
    {
      "title": "Query Modifiers in MongoDB",
      "topics": [
        "Limit() method in MongoDB",
        "Skip() method in MongoDB",
        "Let’s Revise"
      ]
    }
  ]
}

course_data_Redis={
"title": "Redis",
"lessons": [
{
"title": "Getting Started With Redis",
"topics": [
"Overview Of Redis",
"Why Redis?",
"Recap"
]
},
{
"title": "Environment Setup",
"topics": [
"Installing Redis",
"Redis Configuration",
"Recap"
]
},
{
"title": "Data Types In Redis",
"topics": [
"Working With Strings",
"Redis Lists",
"What Are Sets?",
"Hashes In Redis",
"Quiz",
"PRO"
]
},
{
"title": "Redis Commands",
"topics": [
"Strings Commands",
"Lists Commands",
"Sets Commands in Redis",
"Redis Hash Commands",
"Let’s Revise"
]
},
{
"title": "Sorting And Communication Commands",
"topics": [
"Sorting In Redis",
"Redis Publish/Subscribe",
"Recap"
]
},
{
"title": "Transactions In Redis",
"topics": [
"Understanding Transactions",
"Transaction Commands",
"Let's Revise"
]
},
{
"title": "Scripting And Connections",
"topics": [
"Redis Scripting",
"Connection in Redis",
"Recap"
]
}
]
}

course_data_Nodejs = {
  
  "title": "Node.js",
  "lessons": [
    {
      "title": "Introduction to Node.js",
      "topics": [
        "What is Node.js?",
        "History of node.js",
        "Let’s Revise"
      ]
    },
    {
      "title": "Let's get started",
      "topics": [
        "Your First Node Program",
        "Components of Node.js",
        "Let’s Revise"
      ]
    },
    {
      "title": "Asynchronous & non-blocking",
      "topics": [
        "Non-blocking nature",
        "Single-threaded",
        "Let’s Revise"
      ]
    },
    {
      "title": "Modules",
      "topics": [
        "What are modules?",
        "Types of modules",
        "How to use core modules?",
        "How to use local module?",
        "Let’s Revise"
      ]
    },
    {
      "title": "Callback in Node",
      "topics": [
        "Callback functions",
        "Let's do some coding",
        "Let’s Revise"
      ]
    },
    {
      "title": "Streams",
      "topics": [
        "Introduction to streams",
        "Event emitter in streams",
        "Let's Revise"
      ]
    },
    {
      "title": "Node.js REST API",
      "topics": [
        "Introduction to REST",
        "What is API?",
        "Let’s Revise"
      ]
    }
  ]
}

course_data_ExpressJS = {
"title": "Express JS",
"lessons": [
{
"title": "Intro to the world of APIs and Frameworks",
"topics": [
"Understanding Frameworks",
"Asynchronous nature of Express .Js",
"Quiz time",
]
},
{
"title": "A look into the world of Express.Js",
"topics": [
"Achieving Acceleration",
"A Deeper insight into APIs",
"Summarization"
]
},
{
"title": "Enter the world of NPM and API",
"topics": [
"High speed express.Js features..",
"To add more detailing to your setup",
"A look upon what we have learned"
]
},

{
"title": "Apps and Functions",
"topics": [
"Basic Concepts",
"Your 1st App",
"Let’s Revise"
]
},
{
"title": "Routing",
"topics": [
"Calling and Initializing",
"Route Parameters",
"Let’s Revise"
]
},
{
"title": "Methods(Rest API)",
"topics": [
"Popular methods to keep in mind",
"Additional methods under response object()",
"Let’s Revise"
]
},
{
"title": "Static or Dynamic",
"topics": [
"The World of CSS,MVC & more",
"Some additional important aspects!",
"Let’s Revise"
]
}
]
}


# -----------------------------
# Seeder
# -----------------------------
def seed(db: Session):
    course_title = normalize_text(course_data["title"])

    # ✅ Correct query style
    course = db.query(Course).filter(Course.title == course_title).first()

    if not course:
        course = Course(title=course_title)
        db.add(course)
        db.flush()  # get course.id

    for lesson_index, lesson_data in enumerate(course_data["lessons"]):
        lesson_title = normalize_text(lesson_data["title"])

        lesson = (
            db.query(Lesson)
            .filter(
                Lesson.title == lesson_title,
                Lesson.course_id == course.id
            )
            .first()
        )

        if not lesson:
            lesson = Lesson(
                title=lesson_title,
                course_id=course.id,
                order_index=lesson_index
            )
            db.add(lesson)
            db.flush()

        for topic_index, topic_title in enumerate(lesson_data["topics"]):
            topic_title = normalize_text(topic_title)

            exists = (
                db.query(Topic)
                .filter(
                    Topic.title == topic_title,
                    Topic.lesson_id == lesson.id
                )
                .first()
            )

            if not exists:
                topic = Topic(
                    title=topic_title,
                    lesson_id=lesson.id,
                    course_id=course.id,
                    order_index=topic_index
                )
                db.add(topic)

    db.commit()
    print(f"Course [{course_title}] seeded successfully.")


# -----------------------------
# Run directly
# -----------------------------
if __name__ == "__main__":
    db = SessionLocal()

    try:
        seed(db)
    finally:
        db.close()

