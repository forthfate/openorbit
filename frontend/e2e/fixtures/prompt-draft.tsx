import { createRoot } from 'react-dom/client'
import { AssetsPage } from '../../src/features/assets/page'
import { ToastProvider } from '../../src/components/ui/toast'
import { resolveLocale } from '../../src/locales'
import '../../src/styles.css'
import '../../src/theme-overrides.css'

const locale = resolveLocale(new URLSearchParams(location.search).get('locale'))
localStorage.setItem('orbit.locale', locale)
const noop = () => {}
const refresh = async () => {}

createRoot(document.getElementById('root')!).render(
  <ToastProvider>
    <AssetsPage
      locale={locale}
      promptTemplates={[{
        id: 'draft-regression', name: 'Draft regression template', version: 2,
        content: 'Current prompt',
        versions: [{ version: 1, content: 'Previous prompt' }, { version: 2, content: 'Current prompt' }],
      }]}
      workflows={[]} runners={[]} testCaseSets={[]}
      executionEnvironments={[]} targetEnvironments={[]} profiles={[]}
      settings={{ profile_name: '', provider: '', model: '', endpoint: '', region: '', secret_env: '' }}
      setSettings={noop} test={noop} save={refresh} tested={false}
      onRefresh={refresh} onCreateWorkflow={refresh} onUpdateWorkflow={refresh} onDelete={noop}
    />
  </ToastProvider>,
)
