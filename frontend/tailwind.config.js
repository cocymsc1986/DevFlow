/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          base: '#0a0a0f',
          surface: '#111118',
          elevated: '#1a1a24',
          overlay: '#22222f',
        },
        accent: {
          DEFAULT: '#fbbf24',
          dim: '#92400e',
        },
        success: '#34d399',
        error: '#f87171',
        text: {
          primary: '#e2e2ef',
          muted: '#6b6b8a',
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      animation: {
        pulse: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
