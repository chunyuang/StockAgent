/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  // 使用 class 策略实现暗色模式
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 主色调 - 深邃蓝
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        // 股票涨跌颜色 (A股规则：红涨绿跌) - 柔和红/翡翠绿
        stock: {
          up: '#F23645',           // 柔和红
          'up-bg': 'rgba(242, 54, 69, 0.1)',
          down: '#089981',         // 翡翠绿
          'down-bg': 'rgba(8, 153, 129, 0.1)',
          flat: '#64748b',
        },
        // 信号颜色
        signal: {
          buy: '#f23645',
          sell: '#089981',
          hold: '#f59e0b',
        },
        // 背景色系
        surface: {
          base: 'var(--bg-base)',
          elevated: 'var(--bg-elevated)',
          muted: 'var(--bg-muted)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'PingFang SC', 'Microsoft YaHei', '-apple-system', 'sans-serif'],
        mono: ['SF Mono', 'JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'card': 'var(--shadow-card)',
        'card-hover': 'var(--shadow-md)',
        'glow': 'var(--shadow-glow)',
        'xs': 'var(--shadow-xs)',
        'sm': 'var(--shadow-sm)',
        'md': 'var(--shadow-md)',
        'lg': 'var(--shadow-lg)',
        'xl': 'var(--shadow-xl)',
      },
      borderRadius: {
        'xs': 'var(--radius-xs)',
        'sm': 'var(--radius-sm)',
        'md': 'var(--radius-md)',
        'lg': 'var(--radius-lg)',
        'xl': 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
      },
      backgroundColor: {
        'base': 'var(--bg-base)',
        'elevated': 'var(--bg-elevated)',
        'surface': 'var(--bg-surface)',
        'muted': 'var(--bg-muted)',
        'subtle': 'var(--bg-subtle)',
        'inset': 'var(--bg-inset)',
      },
      textColor: {
        'primary': 'var(--text-primary)',
        'secondary': 'var(--text-secondary)',
        'tertiary': 'var(--text-tertiary)',
        'muted': 'var(--text-muted)',
      },
      borderColor: {
        'default': 'var(--border-default)',
        'light': 'var(--border-light)',
        'muted': 'var(--border-muted)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'scale-in': 'scaleIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-down': 'slideDown 0.3s ease-out',
        'breathe': 'breathe 3s ease-in-out infinite',
        'shimmer': 'shimmer 2s infinite',
        'float': 'float 3s ease-in-out infinite',
        'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        scaleIn: {
          from: { opacity: '0', transform: 'scale(0.95)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          from: { opacity: '0', transform: 'translateY(-10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        breathe: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(59, 130, 246, 0)' },
          '50%': { boxShadow: '0 0 0 8px rgba(59, 130, 246, 0.1)' },
        },
        shimmer: {
          from: { backgroundPosition: '-200% 0' },
          to: { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
      },
      transitionDuration: {
        'fast': '150ms',
        'normal': '200ms',
        'slow': '300ms',
      },
    },
  },
  plugins: [],
  // 避免与 Element Plus 冲突
  corePlugins: {
    preflight: false,
  },
}
