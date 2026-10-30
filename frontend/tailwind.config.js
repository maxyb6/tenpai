/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        slate: { DEFAULT: "#2F3E46", deep: "#354F52" },
        green: { slate: "#52796F" },
        sage: { DEFAULT: "#84A98C", pale: "#CAD2C5" },
        bg: "#E6EAE3",
        warn: { DEFAULT: "#B7853A", soft: "#F3E9D2" },
        danger: { DEFAULT: "#A5524A", soft: "#F2DEDA" },
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans Myanmar", "Noto Sans Khmer", "system-ui", "sans-serif"],
        brand: ["Outfit", "Inter", "sans-serif"],
        local: ["Noto Sans Myanmar", "Noto Sans Khmer", "Inter", "sans-serif"],
      },
    },
  },
  plugins: [],
};
