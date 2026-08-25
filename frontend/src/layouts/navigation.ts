export type AppView = 'overview' | 'findings' | 'sources' | 'chat' | 'history' | 'settings'

export type NavItem = {
  id: AppView
  label: string
  icon: string
  description: string
  group: 'Workspace' | 'Intelligence' | 'Configure'
}

export const NAV_ITEMS: NavItem[] = [
  {
    id: 'overview',
    label: 'Dashboard',
    icon: 'space_dashboard',
    description: 'Live KPIs and charts from your data',
    group: 'Workspace',
  },
  {
    id: 'findings',
    label: 'Findings',
    icon: 'flag',
    description: 'Anomalies and opportunities detected in your data',
    group: 'Workspace',
  },
  {
    id: 'sources',
    label: 'Data Sources',
    icon: 'database',
    description: 'Upload files and connect databases',
    group: 'Workspace',
  },
  {
    id: 'chat',
    label: 'Ask AI',
    icon: 'auto_awesome',
    description: 'Ask questions about your data in plain English',
    group: 'Intelligence',
  },
  {
    id: 'history',
    label: 'Q&A History',
    icon: 'history',
    description: 'Review previous questions and results',
    group: 'Intelligence',
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: 'settings',
    description: 'Branding, colour scheme, and AI provider',
    group: 'Configure',
  },
]

export const NAV_GROUPS: NavItem['group'][] = ['Workspace', 'Intelligence', 'Configure']

export const PAGE_META: Record<AppView, { title: string; subtitle: string }> = {
  overview: {
    title: 'Dashboard',
    subtitle: 'Live performance computed from your connected data',
  },
  findings: {
    title: 'Findings',
    subtitle: 'Signals detected in the data you have connected',
  },
  sources: {
    title: 'Data Sources',
    subtitle: 'Manage and map your business datasets',
  },
  chat: {
    title: 'Ask AI',
    subtitle: 'Natural-language questions answered with SQL over your data',
  },
  history: {
    title: 'Q&A History',
    subtitle: 'Every question asked and the result it returned',
  },
  settings: {
    title: 'Settings',
    subtitle: 'Platform branding and AI provider configuration',
  },
}
