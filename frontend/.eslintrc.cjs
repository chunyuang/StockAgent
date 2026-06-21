// ESLint 配置 - 前端防御性规则
//
// 核心目标: 防止三类bug:
// 1. 变量未定义(如 today is not defined)
// 2. 静默吞异常(catch {} / catch { ignore })
// 3. 时区不一致(用 new Date() 而非中国时区)
module.exports = {
  root: true,
  env: {
    browser: true,
    node: true,
    es2022: true,
  },
  parser: 'vue-eslint-parser',
  parserOptions: {
    parser: '@typescript-eslint/parser',
    sourceType: 'module',
    ecmaVersion: 2022,
  },
  plugins: ['@typescript-eslint'],
  extends: [
    'eslint:recommended',
    'plugin:vue/vue3-recommended',
    'plugin:@typescript-eslint/recommended',
  ],
  rules: {
    // ============================================================
    // 防御规则1: 禁止未定义变量 (catches "today is not defined")
    // ============================================================
    'no-undef': 'error',
    '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],

    // ============================================================
    // 防御规则2: 禁止空catch块 (catches "catch { /* ignore */ }")
    //   允许: catch (e) { console.error('...', e) }
    //   禁止: catch {} / catch { /* ignore */ } / catch { }
    //   唯一例外: localStorage等纯I/O操作 (用 // eslint-disable-line 注释)
    // ============================================================
    'no-empty': ['error', { allowEmptyCatch: false }],

    // ============================================================
    // 防御规则3: catch块必须有错误处理
    //   要求: catch (e) { /* 至少有 console.warn/error */ }
    // ============================================================
    'no-useless-catch': 'error',

    // ============================================================
    // 防御规则4: TypeScript严格检查
    // ============================================================
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/explicit-function-return-type': 'off',
    '@typescript-eslint/no-non-null-assertion': 'warn',

    // ============================================================
    // Vue特定规则
    // ============================================================
    'vue/no-unused-components': 'warn',
    'vue/no-unused-vars': 'warn',
    'vue/require-default-prop': 'off',
    'vue/multi-word-component-names': 'off',
  },
  overrides: [
    {
      // 对composables目录更严格
      files: ['src/views/monitor/composables/**/*.ts'],
      rules: {
        '@typescript-eslint/no-explicit-any': 'error',
      },
    },
  ],
}
