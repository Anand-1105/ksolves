import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0a0a0a",
          surface: "#111111",
          elevated: "#161616",
          hover: "#1a1a1a",
        },
        border: {
          DEFAULT: "#1f1f1f",
          subtle: "#171717",
          strong: "#2a2a2a",
        },
        accent: {
          DEFAULT: "#6366f1",
          hover: "#818cf8",
          muted: "#312e81",
          dim: "#1e1b4b",
        },
        text: {
          primary: "#ffffff",
          secondary: "#a1a1aa",
          muted: "#52525b",
          dim: "#3f3f46",
        },
        resolution: {
          approve: "#22c55e",
          "approve-bg": "#052e16",
          "approve-border": "#14532d",
          deny: "#ef4444",
          "deny-bg": "#2d0a0a",
          "deny-border": "#7f1d1d",
          escalate: "#f59e0b",
          "escalate-bg": "#2d1a00",
          "escalate-border": "#78350f",
        },
        tier: {
          vip: "#f59e0b",
          premium: "#a1a1aa",
          standard: "#52525b",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "-apple-system", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        container: "6px",
        input: "4px",
        badge: "9999px",
      },
      animation: {
        "pulse-border": "pulse-border 2s ease-in-out infinite",
        "fade-up": "fade-up 150ms ease-out",
        "bar-fill": "bar-fill 600ms ease-out forwards",
      },
      keyframes: {
        "pulse-border": {
          "0%, 100%": { borderColor: "#1f1f1f" },
          "50%": { borderColor: "#6366f1" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "bar-fill": {
          "0%": { width: "0%" },
          "100%": { width: "var(--bar-width)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
