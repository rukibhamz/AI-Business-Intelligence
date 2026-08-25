export type AppView = 'overview' | 'findings' | 'sources' | 'chat' | 'history' | 'settings'

export type NavGroup = 'Analyze' | 'Workspace' | 'Configure'

export type NavItem = {
  id: AppView
  label: string
  icon: string
  description: string
  group: NavGroup
}

export const NAV_ITEMS: NavItem[] = [
  {
    id: 'chat',
    label: 'Analysis',
    icon: 'auto_awesome',
    description: 'Ask a question about your data in plain English',
    group: 'Analyze',
  },
  {
    id: 'history',
    label: 'History',
    icon: 'history',
    description: 'Your past chats — reopen and continue any of them',
    group: 'Analyze',
  },
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
    id: 'settings',
    label: 'Settings',
    icon: 'settings',
    description: 'Branding, colour scheme, and AI provider',
    group: 'Configure',
  },
]

export const NAV_GROUPS: NavGroup[] = ['Analyze', 'Workspace', 'Configure']

export const PAGE_META: Record<AppView, { title: string; subtitle: string }> = {
  chat: {
    title: 'Analysis',
    subtitle: 'Ask a question — answered with SQL run against your own data',
  },
  history: {
    title: 'History',
    subtitle: 'Your past chats — open one to pick up where you left off',
  },
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
  settings: {
    title: 'Settings',
    subtitle: 'Platform branding and AI provider configuration',
  },
}
