/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{html,ts}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#1a3c34',
          light:   '#2d5a4e',
          dark:    '#0f2420',
        },
        accent: {
          DEFAULT: '#4CAF50',
          light:   '#81C784',
        },
        danger:  '#ef4444',
        warning: '#f59e0b',
        success: '#22c55e',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
