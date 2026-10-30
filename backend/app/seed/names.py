"""Fictional name parts for sample data. Combinations are random and do not
describe real people. Local-script spellings are drafts for native review."""

# (romanised, Burmese Unicode)
MM_SYLLABLES_F = [
    ("Hnin", "နှင်း"), ("Thida", "သီတာ"), ("Khin", "ခင်"), ("Nwe", "နွယ်"), ("Su", "စု"),
    ("Myat", "မြတ်"), ("Phyu", "ဖြူ"), ("Thu", "သူ"), ("Zar", "ဇာ"), ("Ei", "အိ"),
    ("Mon", "မွန်"), ("Thandar", "သန္တာ"), ("San", "စန်း"), ("Yee", "ရီ"), ("Mya", "မြ"),
    ("Nyein", "ငြိမ်း"), ("Pyae", "ပြည့်"), ("Sandar", "စန္ဒာ"), ("Wai", "ဝေ"), ("Yin", "ယဉ်"),
    ("Moe", "မိုး"), ("Aye", "အေး"), ("Cho", "ချို"), ("Hla", "လှ"), ("May", "မေ"),
]
MM_SYLLABLES_M = [
    ("Aung", "အောင်"), ("Kyaw", "ကျော်"), ("Min", "မင်း"), ("Zaw", "ဇော်"), ("Htet", "ထက်"),
    ("Naing", "နိုင်"), ("Hlaing", "လှိုင်"), ("Win", "ဝင်း"), ("Myint", "မြင့်"), ("Tun", "ထွန်း"),
    ("Soe", "စိုး"), ("Lwin", "လွင်"), ("Thet", "သက်"), ("Paing", "ပိုင်"), ("Hein", "ဟိန်း"),
    ("Kaung", "ကောင်း"), ("Thant", "သန့်"), ("Oo", "ဦး"), ("Maung", "မောင်"), ("Ye", "ရဲ"),
]
MM_HONORIFIC = {"F_old": ("Daw", "ဒေါ်"), "F_young": ("Ma", "မ"), "M_old": ("U", "ဦး"), "M_young": ("Ko", "ကို")}

KH_FAMILY = [
    ("Sok", "សុខ"), ("Chan", "ចាន់"), ("Kim", "គីម"), ("Heng", "ហេង"), ("Meas", "មាស"),
    ("Keo", "កែវ"), ("Nhem", "ញឹម"), ("Phan", "ផាន"), ("Chea", "ជា"), ("Ly", "លី"),
    ("Ouk", "អ៊ុក"), ("Seng", "សេង"), ("Mao", "ម៉ៅ"), ("Sam", "សំ"), ("Prak", "ប្រាក់"),
    ("Touch", "ទូច"), ("Hem", "ហែម"), ("Yim", "យឹម"),
]
KH_GIVEN_F = [
    ("Sophea", "សុភា"), ("Sreymom", "ស្រីមុំ"), ("Bopha", "បុប្ផា"), ("Channary", "ចាន់ណារី"),
    ("Sokha", "សុខា"), ("Pisey", "ពិសី"), ("Rachana", "រចនា"), ("Kunthea", "គន្ធា"),
    ("Sopheap", "សុភាព"), ("Chenda", "ចិន្តា"), ("Malis", "ម្លិះ"), ("Leakhena", "លក្ខិណា"),
    ("Thida", "ធីតា"), ("Sothea", "សុធា"), ("Srey Leak", "ស្រីលក្ខ"), ("Navy", "ណាវី"),
]
KH_GIVEN_M = [
    ("Dara", "ដារ៉ា"), ("Vanna", "វណ្ណា"), ("Vibol", "វិបុល"), ("Rithy", "រិទ្ធី"),
    ("Sovann", "សុវណ្ណ"), ("Piseth", "ពិសិដ្ឋ"), ("Bunthoeun", "ប៊ុនធឿន"), ("Samnang", "សំណាង"),
    ("Visal", "វិសាល"), ("Kosal", "កុសល"),
]

MM_BRANCHES = [
    {"code": "HTY", "name": "Hlaing Tharyar", "name_local": "လှိုင်သာယာ",
     "villages": ["Ward 3", "Ward 7", "Ward 11", "Ward 14", "Ward 18", "Shwe Lin Ban"]},
    {"code": "BGO", "name": "Bago", "name_local": "ပဲခူး",
     "villages": ["Oak Thar Myo Thit", "Zaing Ga Naing", "Ma Hu Ya", "Kyauk Gyi Su", "Nyaung Pin Thar"]},
    {"code": "MDY", "name": "Mandalay Chanmyathazi", "name_local": "ချမ်းမြသာစည်",
     "villages": ["Kan Gyi Kone", "Chan Thar Yar", "Myit Nge", "Pyi Gyi Tagon", "Aung Pin Lal"]},
]
KH_BRANCHES = [
    {"code": "TKO", "name": "Takeo", "name_local": "តាកែវ",
     "villages": ["Prey Kabbas", "Angkor Borei", "Bati", "Samraong", "Tram Kak"]},
    {"code": "KPC", "name": "Kampong Cham", "name_local": "កំពង់ចាម",
     "villages": ["Cheung Prey", "Batheay", "Kang Meas", "Prey Chhor", "Srei Santhor"]},
    {"code": "SRP", "name": "Siem Reap", "name_local": "សៀមរាប",
     "villages": ["Puok", "Prasat Bakong", "Soutr Nikom", "Chi Kraeng", "Banteay Srei"]},
]
