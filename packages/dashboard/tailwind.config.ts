import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      colors: {
        void: "#0a0a0f",
        surface: "#111118",
        elevated: "#16161f",
        "neon-cyan": "#00f5ff",
        "neon-purple": "#8b5cf6",
        "neon-green": "#00ff88",
        "neon-orange": "#ff6b35",
        "neon-red": "#ff2d55",
        "neon-gold": "#ffd700",
      },
      animation: {
        "agent-pulse": "agent-pulse 2s ease-in-out infinite",
        "conviction-rise": "conviction-rise 0.8s cubic-bezier(0.34,1.56,0.64,1) forwards",
        "vote-appear": "parliament-vote 0.4s cubic-bezier(0.34,1.56,0.64,1) forwards",
      },
    },
  },
  plugins: [],
};

export default config;
