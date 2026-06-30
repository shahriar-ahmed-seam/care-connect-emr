import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#e6f3f4",
          100: "#c2e0e2",
          200: "#8fc6ca",
          300: "#5aa9af",
          400: "#2d8a91",
          500: "#0d6e74",
          600: "#0b585d",
          700: "#094649",
          800: "#073538",
          900: "#052527",
        },
        accent: {
          400: "#e8a13c",
          500: "#cc7a14",
        },
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f4f7f8",
          sunken: "#eef3f4",
        },
        ink: {
          DEFAULT: "#1f2933",
          muted: "#46535e",
          subtle: "#5f6b76",
        },
        success: "#0f7b52",
        danger: "#b42318",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        bangla: ["var(--font-bangla)", "var(--font-sans)", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 40, 44, 0.06), 0 4px 16px rgba(16, 40, 44, 0.06)",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
    },
  },
  plugins: [],
};

export default config;
