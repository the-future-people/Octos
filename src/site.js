// ─────────────────────────────────────────────────────────────
// site.js — the one place for Farhat's facts.
// Every page reads from here. Change a fact here, it changes everywhere.
// ─────────────────────────────────────────────────────────────

export const company = {
  name: 'Farhat Printing Press',
  shortName: 'Farhat',
  url: 'https://farhatprintingpress.com',
  email: 'info@farhatprintingpress.com',
  founded: 2023,
  tagline: "Accra's trusted printing partner",
}

// One number for calls and WhatsApp (Octos answers on WhatsApp).
export const phone = {
  display: '+233 55 196 9777',
  e164: '+233551969777',
}

export const telHref = `tel:${phone.e164}`

// Print Octos, the online ordering site. Becomes order.farhatprintingpress.com at cutover.
export const orderUrl = 'https://print-octos.vercel.app'

// Opens a WhatsApp chat with Octos, message prefilled.
export function waHref(message = "Hi Farhat, I'd like to send a print job.") {
  return `https://wa.me/${phone.e164.replace('+', '')}?text=${encodeURIComponent(message)}`
}

// Times are Accra time (GMT, no daylight saving). 24h "HH:MM".
export const hours = [
  { days: 'Monday – Friday', open: '07:30', close: '19:30' },
  { days: 'Saturday', open: '09:00', close: '17:30' },
  { days: 'Sunday', open: null, close: null },
]

// Used by "Open now" badges. Day index: 0 = Sunday … 6 = Saturday.
// Call only in the browser (inside useEffect) — at build time it would bake in the build's clock.
const hoursByDay = [hours[2], hours[0], hours[0], hours[0], hours[0], hours[0], hours[1]]
export function isOpenNow(now = new Date()) {
  const accra = new Date(now.toLocaleString('en-US', { timeZone: 'Africa/Accra' }))
  const today = hoursByDay[accra.getDay()]
  if (!today.open) return false
  const mins = accra.getHours() * 60 + accra.getMinutes()
  const toMins = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))
  return mins >= toMins(today.open) && mins < toMins(today.close)
}

// Format "07:30" → "7:30am"
export function fmtTime(t) {
  if (!t) return ''
  let [h, m] = t.split(':').map(Number)
  const ap = h >= 12 ? 'pm' : 'am'
  h = h % 12 || 12
  return `${h}:${String(m).padStart(2, '0')}${ap}`
}

export const branches = [
  {
    id: 'westland',
    name: 'Westland Branch',
    area: 'Westland, Accra',
    address: '63 Westlands Ave, Accra',
    gps: 'GE-328-6296',
    open: true,
    // Exact pin for the map. In Google Maps: right-click the shop → click the numbers to copy them.
    // e.g. coords: [5.6512, -0.1987]. While null, the Contact page shows a directions card instead of a map.
    coords: [5.656012, -0.208297], // from GhanaPost GPS GE-328-6296 (Westlands Avenue, Papao)
  },
  { id: 'madina', name: 'Madina Branch', area: 'Madina, Accra', open: false },
  { id: 'kwashieman', name: 'Kwashieman Branch', area: 'Kwashieman, Accra', open: false },
]

export const mainBranch = branches[0]

// Directions link: the exact pin once coords are set, otherwise the street address.
export function mapsHref(b = mainBranch) {
  const q = b.coords ? b.coords.join(',') : b.address
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(q)
}

export function mapEmbedSrc(b = mainBranch) {
  return b.coords ? `https://www.google.com/maps?q=${b.coords.join(',')}&z=17&output=embed` : null
}

// No own delivery — customers send a rider to collect.
export const collection =
  'Collect at the branch, or send any rider or ride-hailing driver to pick up for you.'

export const stats = [
  { value: '5,000+', label: 'Jobs completed' },
  { value: '30+', label: 'Businesses served' },
  { value: String(2023), label: 'Serving Accra since' },
]

// Filter chips on the Services page.
export const serviceCategories = [
  { id: 'print', label: 'Print' },
  { id: 'large-format', label: 'Large Format' },
  { id: 'finishing', label: 'Finishing' },
  { id: 'branding', label: 'Branding' },
  { id: 'packaging', label: 'Packaging' },
]

// available: false → shown as "Coming soon" instead of hidden.
export const services = [
  {
    id: 'printing',
    name: 'Printing',
    category: 'print',
    summary: 'A4, A3 and custom sizes, in colour or black & white.',
    available: true,
  },
  {
    id: 'flyers-cards',
    name: 'Flyers & Business Cards',
    category: 'print',
    summary: 'A5 and A4 flyers on art paper, business cards in boxes of 100.',
    available: true,
  },
  {
    id: 'books',
    name: 'Books & Magazines',
    category: 'print',
    summary: 'Books, magazines and reports, in small runs or bulk.',
    available: true,
  },
  {
    id: 'passport-photos',
    name: 'Passport & Photos',
    category: 'print',
    summary: 'British and American passport sizes, and 4 × 6 photo prints.',
    available: true,
  },
  {
    id: 'banners',
    name: 'Banners & Signage',
    category: 'large-format',
    summary: 'Flexy banners, roll-up stands, backdrops and outdoor signage.',
    available: true,
  },
  {
    id: 'stickers',
    name: 'Stickers & Labels',
    category: 'large-format',
    summary: 'SAV stickers, cut to shape, labels and reflective stickers.',
    available: true,
  },
  {
    id: 'binding',
    name: 'Binding',
    category: 'finishing',
    summary: 'Ring binding for reports, proposals, books and notes.',
    available: true,
  },
  {
    id: 'lamination',
    name: 'Lamination',
    category: 'finishing',
    summary: 'Documents, ID cards, menus and posters, made to last.',
    available: true,
  },
  {
    id: 'dtf-embroidery',
    name: 'DTF & Embroidery',
    category: 'branding',
    summary: 'Branded T-shirts, polos, caps and corporate wear.',
    available: true,
  },
  {
    id: 'packaging',
    name: 'Packaging',
    category: 'packaging',
    summary: 'Custom boxes, food boxes, paper bags and product packaging.',
    available: true,
  },
]

// Smaller services listed as text, not cards.
export const alsoAvailable = [
  'Scanning (sent by WhatsApp, email or flash drive)',
  'Typing',
  'Forms & filing assistance',
  'Envelopes & clear bags',
  'Offset printing from 1,000 pieces',
]

// Solutions page sections (also the Solutions dropdown).
export const solutions = [
  { id: 'education', name: 'Education', summary: 'Printing for schools, colleges and training institutions.' },
  { id: 'corporate', name: 'Corporate', summary: 'Branded print and marketing materials for businesses.' },
  { id: 'events', name: 'Events', summary: 'Banners, backdrops, programmes and full event branding.' },
  { id: 'retail', name: 'Retail & Packaging', summary: 'Boxes, bags, labels and product packaging.' },
  { id: 'organisations', name: 'Organisations', summary: 'Print and branding for NGOs, churches and associations.' },
  { id: 'personal', name: 'Personal', summary: 'Everyday prints, documents, photos and gifts.' },
  { id: 'tender', name: 'Tender documents', summary: 'Formatting, printing, binding and packaging for tender submissions.' },
]

// Our Work gallery. Empty until real jobs are photographed (with the client's OK).
// Photos go in public/work/ as .webp, about 1200px wide. Category = a serviceCategories id.
// Example:
// { id: 'school-banner', title: 'School admission banner', category: 'large-format',
//   summary: '10 x 4 ft flexy banner with eyelets', image: '/work/school-banner.webp' },
export const work = []

export const nav = [
  { to: '/', label: 'Home' },
  { to: '/services', label: 'Services' },
  { to: '/solutions', label: 'Solutions' },
  { to: '/our-work', label: 'Our Work', hidden: true }, // until real jobs are photographed
  { to: '/about', label: 'About' },
  { to: '/contact', label: 'Contact' },
]

export const footerLinks = [
  { href: '/solutions#tender', label: 'Tender documents' },
  // Django's careers page. Works today; becomes app.farhatprintingpress.com/careers/ at cutover.
  { href: 'https://farhatprintingpress.com/careers/', label: 'Careers', external: true },
  { href: '/contact#partners', label: 'Become a partner' },
]
