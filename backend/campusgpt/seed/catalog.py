"""Fixed reference data for the synthetic university: departments, programs, course titles.

Everything here is fictional. Course titles are generic curriculum names, not copied from
any real university's syllabus.
"""

# code -> name
DEPARTMENTS = {
    "CSE": "Computer Science and Engineering",
    "ECE": "Electronics and Communication Engineering",
    "ME": "Mechanical Engineering",
    "CE": "Civil Engineering",
    "MGT": "Management Studies",
}

# (code, department, name, duration in semesters, roll-number prefix, share of students,
#  tuition fee per semester in rupees)
PROGRAMS = [
    ("BTECH-CSE", "CSE", "B.Tech Computer Science and Engineering", 8, "CSE", 0.20, 185_000),
    ("BTECH-CSE-AIML", "CSE", "B.Tech CSE (Artificial Intelligence and Machine Learning)", 8,
     "AIML", 0.10, 195_000),
    ("BTECH-CSE-CS", "CSE", "B.Tech CSE (Cyber Security)", 8, "CYS", 0.10, 195_000),
    ("BTECH-ECE", "ECE", "B.Tech Electronics and Communication Engineering", 8, "ECE", 0.14,
     160_000),
    ("BTECH-ME", "ME", "B.Tech Mechanical Engineering", 8, "ME", 0.12, 145_000),
    ("BTECH-CE", "CE", "B.Tech Civil Engineering", 8, "CE", 0.10, 145_000),
    ("BBA", "MGT", "Bachelor of Business Administration", 6, "BBA", 0.16, 120_000),
    ("BBA-BA", "MGT", "BBA (Business Analytics)", 6, "BBABA", 0.08, 130_000),
]

# department -> semester -> five course titles. Programs in a department share its courses.
COURSES = {
    "CSE": {
        1: ["Programming in C", "Engineering Mathematics I", "Engineering Physics",
            "Basic Electrical Engineering", "Communication Skills"],
        2: ["Data Structures", "Engineering Mathematics II", "Engineering Chemistry",
            "Digital Logic Design", "Environmental Studies"],
        3: ["Database Management Systems", "Object-Oriented Programming with Java",
            "Discrete Mathematics", "Computer Organization and Architecture",
            "Design and Analysis of Algorithms"],
        4: ["Operating Systems", "Theory of Computation", "Probability and Statistics",
            "Microprocessors and Interfacing", "Web Technologies"],
        5: ["Computer Networks", "Software Engineering", "Machine Learning", "Compiler Design",
            "Information Security"],
        6: ["Artificial Intelligence", "Cloud Computing", "Distributed Systems", "Data Mining",
            "Mobile Application Development"],
        7: ["Cryptography and Network Security", "Big Data Analytics", "Deep Learning",
            "Internet of Things", "Major Project I"],
        8: ["Major Project II", "Blockchain Technology", "Natural Language Processing",
            "Professional Ethics", "Industrial Internship"],
    },
    "ECE": {
        1: ["Engineering Mathematics I", "Engineering Physics", "Basic Electrical Engineering",
            "Programming in C", "Communication Skills"],
        2: ["Engineering Mathematics II", "Network Theory", "Electronic Devices",
            "Engineering Chemistry", "Environmental Studies"],
        3: ["Analog Circuits", "Signals and Systems", "Digital Electronics",
            "Electromagnetic Theory", "Engineering Mathematics III"],
        4: ["Analog Communication", "Linear Integrated Circuits",
            "Microprocessors and Microcontrollers", "Control Systems",
            "Probability and Random Processes"],
        5: ["Digital Communication", "Digital Signal Processing", "VLSI Design",
            "Antennas and Wave Propagation", "Embedded Systems"],
        6: ["Microwave Engineering", "Optical Communication", "Wireless Communication",
            "Computer Networks", "Information Theory and Coding"],
        7: ["Satellite Communication", "Internet of Things", "Radar Systems", "Image Processing",
            "Major Project I"],
        8: ["Major Project II", "Mobile Communication Networks",
            "Machine Learning for Signal Processing", "Professional Ethics",
            "Industrial Internship"],
    },
    "ME": {
        1: ["Engineering Mathematics I", "Engineering Physics", "Engineering Graphics",
            "Basic Electrical Engineering", "Communication Skills"],
        2: ["Engineering Mathematics II", "Engineering Mechanics", "Engineering Chemistry",
            "Workshop Practice", "Environmental Studies"],
        3: ["Thermodynamics", "Strength of Materials", "Manufacturing Processes",
            "Material Science", "Engineering Mathematics III"],
        4: ["Fluid Mechanics", "Kinematics of Machines", "Applied Thermodynamics",
            "Machine Drawing", "Metrology and Measurements"],
        5: ["Heat and Mass Transfer", "Dynamics of Machines", "Design of Machine Elements",
            "Manufacturing Technology", "Industrial Engineering"],
        6: ["Refrigeration and Air Conditioning", "Finite Element Analysis",
            "Automobile Engineering", "CAD/CAM", "Operations Research"],
        7: ["Power Plant Engineering", "Robotics", "Renewable Energy Systems", "Mechatronics",
            "Major Project I"],
        8: ["Major Project II", "Additive Manufacturing", "Total Quality Management",
            "Professional Ethics", "Industrial Internship"],
    },
    "CE": {
        1: ["Engineering Mathematics I", "Engineering Physics", "Engineering Graphics",
            "Basic Civil Engineering", "Communication Skills"],
        2: ["Engineering Mathematics II", "Engineering Mechanics", "Engineering Chemistry",
            "Building Materials", "Environmental Studies"],
        3: ["Surveying", "Fluid Mechanics", "Strength of Materials", "Engineering Geology",
            "Engineering Mathematics III"],
        4: ["Structural Analysis I", "Hydraulics and Hydraulic Machines", "Concrete Technology",
            "Soil Mechanics", "Building Planning and Drawing"],
        5: ["Structural Analysis II", "Design of Concrete Structures", "Geotechnical Engineering",
            "Transportation Engineering", "Water Resources Engineering"],
        6: ["Design of Steel Structures", "Environmental Engineering", "Estimation and Costing",
            "Foundation Engineering", "Remote Sensing and GIS"],
        7: ["Construction Management", "Prestressed Concrete", "Earthquake Engineering",
            "Bridge Engineering", "Major Project I"],
        8: ["Major Project II", "Advanced Structural Design", "Smart Cities",
            "Professional Ethics", "Industrial Internship"],
    },
    "MGT": {
        1: ["Principles of Management", "Business Economics", "Financial Accounting",
            "Business Communication", "Business Mathematics"],
        2: ["Organizational Behaviour", "Macroeconomics", "Cost Accounting",
            "Business Statistics", "Environmental Studies"],
        3: ["Marketing Management", "Human Resource Management", "Corporate Finance",
            "Business Law", "Management Information Systems"],
        4: ["Operations Management", "Research Methodology", "Consumer Behaviour",
            "Income Tax Law", "Entrepreneurship Development"],
        5: ["Strategic Management", "International Business", "Digital Marketing",
            "Business Analytics", "Summer Internship Project"],
        6: ["Business Ethics and Governance", "Supply Chain Management", "E-Commerce",
            "Project Management", "Final Research Project"],
    },
}

FACULTY_PER_DEPARTMENT = {"CSE": 40, "ECE": 28, "ME": 26, "CE": 24, "MGT": 30}
DESIGNATION_WEIGHTS = {"Professor": 0.15, "Associate Professor": 0.25,
                       "Assistant Professor": 0.60}

SECTION_SIZE = 60          # maximum students per section
EXAM_FEE = 3_500           # end-term examination fee per student, rupees

# Fixed national holidays (month, day): no classes.
HOLIDAYS = [(1, 26), (8, 15), (10, 2)]

# kind -> (title, body). Dates in the text always match the generated schedule.
NOTICE_TEMPLATES = {
    "tuition": ("Tuition fee due for {term}",
                ("Tuition fees for {term} must be paid by {date}. A late fee is charged on "
                "payments received after the due date.")),
    "guidelines": ("Assignment submission guidelines",
                   ("All assignments must be submitted on the learning portal before the "
                   "deadline. Late submissions are accepted for 48 hours with a penalty, as per "
                   "the course plan.")),
    "mid_term": ("Mid-term examination schedule released ({dept})",
                 ("Mid-term examinations for {dept} students begin on {date}. The timetable is "
                 "on the examination portal; carry your identity card to the examination hall.")),
    "library": ("Library hours extended during examinations",
                ("The central library will remain open until 11 pm from {date} until the end of "
                "the examination period.")),
    "holiday": ("Campus closed on {holiday}",
                ("The campus will remain closed on {date} on account of {holiday}. Classes "
                "scheduled for that day will be rescheduled by the departments.")),
    "attendance": ("Attendance shortage warning ({dept})",
                   ("Students of {dept} whose attendance is below the required minimum in any "
                   "course must meet their faculty mentor before {date}.")),
    "exam_fee": ("Last date for end-term examination fee",
                 ("The end-term examination fee of Rs {exam_fee} must be paid by {date}. "
                 "Students with unpaid fees will not be issued admit cards.")),
    "guest": ("Guest lecture: {topic}",
              ("The {dept} department invites all students to a guest lecture on {topic} on "
              "{date} in the main auditorium.")),
    "hackathon": ("Hackathon registrations open",
                  ("Registrations for the inter-department hackathon close on {date}. Teams of "
                  "two to four students may register on the student portal.")),
    "scholarship": ("Scholarship applications invited",
                    ("Applications for the merit-cum-means scholarship are open until {date}. "
                    "Eligible students should submit their documents to the scholarship office.")),
    "placement": ("Pre-placement talk for final-year students ({dept})",
                  ("A pre-placement talk for final-year {dept} students will be held on {date}. "
                  "Attendance is mandatory for registered students.")),
}
NOTICE_COUNT = 100

GUEST_LECTURE_TOPICS = [
    "Responsible AI", "Cyber Security Careers", "Sustainable Construction", "Electric Vehicles",
    "Start-up Funding", "Cloud-Native Applications", "5G Networks", "Robotics in Industry",
    "Financial Markets", "Data Privacy Law",
]

HOLIDAY_NAMES = {(1, 26): "Republic Day", (8, 15): "Independence Day",
                 (10, 2): "Gandhi Jayanti"}
