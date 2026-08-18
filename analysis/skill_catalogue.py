from .skill_normalisation import normalise_skill_key


CATEGORY_PROGRAMMING = 'Programming & Software'
CATEGORY_DATA = 'Data & Analytics'
CATEGORY_LABORATORY = 'Laboratory & Scientific Methods'
CATEGORY_FINANCE = 'Finance & Business Tools'
CATEGORY_MARKETING = 'Marketing & Digital Tools'
CATEGORY_ENGINEERING = 'Engineering & Design Tools'
CATEGORY_TRANSFERABLE = 'Transferable / Professional Skills'
CATEGORY_OTHER = 'Other / Domain Skill'


SKILL_CATALOGUE_ENTRIES = [
    {
        'canonical': 'Python',
        'aliases': ['python'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'SQL',
        'aliases': ['sql', 'mysql', 'postgresql', 'postgres'],
        'category': CATEGORY_DATA,
        'source': 'catalogue',
    },
    {
        'canonical': 'Git',
        'aliases': ['git', 'github', 'gitlab'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Django',
        'aliases': ['django'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'REST APIs',
        'aliases': ['rest api', 'rest APIs', 'restful api', 'restful APIs'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'JavaScript',
        'aliases': ['javascript', 'js'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'HTML',
        'aliases': ['html', 'html5'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'CSS',
        'aliases': ['css', 'css3'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Bootstrap',
        'aliases': ['bootstrap'],
        'category': CATEGORY_PROGRAMMING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Machine Learning',
        'aliases': ['machine learning', 'ml'],
        'category': CATEGORY_DATA,
        'source': 'catalogue',
    },
    {
        'canonical': 'Artificial Intelligence',
        'aliases': ['artificial intelligence', 'ai'],
        'category': CATEGORY_DATA,
        'source': 'catalogue',
    },
    {
        'canonical': 'ChemDraw',
        'aliases': ['chemdraw'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'HPLC',
        'aliases': ['hplc', 'high-performance liquid chromatography', 'high performance liquid chromatography'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'GC-MS',
        'aliases': ['gc-ms', 'gc ms', 'gc–ms'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'NMR spectroscopy',
        'aliases': ['nmr spectroscopy', 'nmr'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'Organic synthesis',
        'aliases': ['organic synthesis'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'Laboratory safety',
        'aliases': ['laboratory safety', 'lab safety'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'Analytical method development',
        'aliases': ['analytical method development'],
        'category': CATEGORY_LABORATORY,
        'source': 'catalogue',
    },
    {
        'canonical': 'Excel',
        'aliases': ['excel', 'microsoft excel'],
        'category': CATEGORY_FINANCE,
        'source': 'catalogue',
    },
    {
        'canonical': 'Financial modelling',
        'aliases': ['financial modelling', 'financial modeling'],
        'category': CATEGORY_FINANCE,
        'source': 'catalogue',
    },
    {
        'canonical': 'IFRS',
        'aliases': ['ifrs', 'international financial reporting standards'],
        'category': CATEGORY_FINANCE,
        'source': 'catalogue',
    },
    {
        'canonical': 'Bloomberg Terminal',
        'aliases': ['bloomberg terminal'],
        'category': CATEGORY_FINANCE,
        'source': 'catalogue',
    },
    {
        'canonical': 'SEO',
        'aliases': ['seo', 'search engine optimisation', 'search engine optimization'],
        'category': CATEGORY_MARKETING,
        'source': 'catalogue',
    },
    {
        'canonical': 'CRM',
        'aliases': ['crm', 'customer relationship management'],
        'category': CATEGORY_MARKETING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Google Analytics',
        'aliases': ['google analytics'],
        'category': CATEGORY_MARKETING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Paid media',
        'aliases': ['paid media'],
        'category': CATEGORY_MARKETING,
        'source': 'catalogue',
    },
    {
        'canonical': 'SolidWorks',
        'aliases': ['solidworks'],
        'category': CATEGORY_ENGINEERING,
        'source': 'catalogue',
    },
    {
        'canonical': 'CAD',
        'aliases': ['cad', 'computer aided design', 'computer-aided design'],
        'category': CATEGORY_ENGINEERING,
        'source': 'catalogue',
    },
    {
        'canonical': 'FEA',
        'aliases': ['fea', 'finite element analysis'],
        'category': CATEGORY_ENGINEERING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Manufacturing processes',
        'aliases': ['manufacturing processes', 'manufacturing process'],
        'category': CATEGORY_ENGINEERING,
        'source': 'catalogue',
    },
    {
        'canonical': 'Stakeholder management',
        'aliases': ['stakeholder management'],
        'category': CATEGORY_TRANSFERABLE,
        'source': 'catalogue',
    },
    {
        'canonical': 'Project management',
        'aliases': ['project management'],
        'category': CATEGORY_TRANSFERABLE,
        'source': 'catalogue',
    },
    {
        'canonical': 'Communication',
        'aliases': ['communication', 'communications'],
        'category': CATEGORY_TRANSFERABLE,
        'source': 'catalogue',
    },
    {
        'canonical': 'Data analysis',
        'aliases': ['data analysis', 'data analytics'],
        'category': CATEGORY_DATA,
        'source': 'catalogue',
    },
]


SKILL_CATALOGUE = [
    (entry['canonical'], entry['aliases'])
    for entry in SKILL_CATALOGUE_ENTRIES
]


def catalogue_lookup():
    """Return catalogue entries keyed by canonical and alias normalisation keys."""
    lookup = {}
    for entry in SKILL_CATALOGUE_ENTRIES:
        lookup[normalise_skill_key(entry['canonical'])] = entry
        for alias in entry['aliases']:
            lookup[normalise_skill_key(alias)] = entry
    return lookup


def get_catalogue_entry(skill):
    """Return a catalogue entry for a canonical skill or known alias."""
    return catalogue_lookup().get(normalise_skill_key(skill))


def get_aliases_for_skill(skill):
    """Return configured aliases for a skill, or the skill itself for dynamic candidates."""
    entry = get_catalogue_entry(skill)
    if entry:
        return entry['aliases']
    return [skill]


def get_category_for_skill(skill):
    """Return the display category for a known skill or the generic dynamic category."""
    entry = get_catalogue_entry(skill)
    if entry:
        return entry['category']
    return CATEGORY_OTHER


def get_source_for_skill(skill):
    """Return whether a skill came from the catalogue or dynamic candidate discovery."""
    entry = get_catalogue_entry(skill)
    if entry:
        return entry['source']
    return 'candidate'
