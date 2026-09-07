import { Activity, BarChart3, Boxes, FileCode2, Play, Settings, Sparkles } from 'lucide-react'
import { SiGithub } from 'react-icons/si'
import type { ReactNode } from 'react'
import type { Page } from '../domain/models'
import type { Locale } from '../locales'
import { locales } from '../locales'
import { ChatAssistant } from '../components/chat-assistant'

export function AppShell({page,setPage,locale,theme,headerAction,children}:{page:Page;setPage:(page:Page)=>void;locale:Locale;theme:string;headerAction?:ReactNode;children:ReactNode}){
  const t=locales[locale]
  const pageDescriptions:Record<Locale,Record<Page,string>>={
    en:{dashboard:'Monitor evaluation health, recent activity, and operational events at a glance.',assets:'Manage the reusable environments, runners, templates, test cases, and workflows used by evaluations.',builds:'Combine reusable assets into evaluation configurations and start or test their runs.',runs:'Inspect active and completed evaluation runs, their evidence, and approval decisions.',improvements:'Review evaluation feedback, proposed improvements, and their outcomes over time.',settings:'Configure console preferences, AI connection profiles, and operational manager instructions.'},
    ko:{dashboard:'평가 운영 상태, 최근 활동, 운영 이벤트를 한눈에 확인합니다.',assets:'평가에 사용하는 재사용 환경, 러너, 템플릿, 테스트 케이스, 워크플로를 관리합니다.',builds:'재사용 자산을 평가 구성으로 조합하고 실행하거나 테스트합니다.',runs:'진행 중이거나 완료된 평가 실행, 근거, 승인 결정을 확인합니다.',improvements:'평가 피드백, 개선 제안, 시간에 따른 결과를 검토합니다.',settings:'콘솔 기본 설정, AI 연결 프로필, 운영 관리자 지시문을 관리합니다.'},
    ja:{dashboard:'評価の運用状態、最近のアクティビティ、運用イベントを一目で確認します。',assets:'評価で使う再利用可能な環境、ランナー、テンプレート、テストケース、ワークフローを管理します。',builds:'再利用可能なアセットを評価構成に組み合わせ、実行またはテストします。',runs:'進行中・完了済みの評価実行、証跡、承認判断を確認します。',improvements:'評価フィードバック、改善提案、時間に応じた成果を確認します。',settings:'コンソール設定、AI 接続プロファイル、運用管理者向け指示を管理します。'},
  }
  const navigation:[Page,ReactNode,string][]=[['dashboard',<Activity size={17}/>,t.dashboard],['assets',<Boxes size={17}/>,t.assets],['builds',<FileCode2 size={17}/>,t.builds],['runs',<Play size={17}/>,t.runs],['improvements',<BarChart3 size={17}/>,t.improvements],['settings',<Settings size={17}/>,t.settings]]
  const dashboardRepositoryLink=page==='dashboard'&&<a className="dashboard-repository-link" href="https://github.com/forthfate/openorbit" target="_blank" rel="noreferrer"><SiGithub size={16}/>GitHub Repository</a>
  return <main data-theme={theme==='midnight'?'midnight':undefined}><aside><div className="brand"><Sparkles size={20}/><div><span>OpenOrbit</span><small>{__OPENORBIT_VERSION__}</small></div></div><nav>{navigation.map(([id,icon,label])=><button className={page===id?'active':''} onClick={()=>setPage(id)} key={id}>{icon}{label}</button>)}</nav></aside><section className="content"><header><div className="page-header-copy"><h1>{t[page]}</h1><p className="sub">{pageDescriptions[locale][page]}</p></div><div className="page-header-actions">{dashboardRepositoryLink}{headerAction}</div></header>{children}<footer><span>© insighta cloud Inc.</span><a className="github-link" href="https://github.com/forthfate/openorbit" target="_blank" rel="noreferrer" aria-label="OpenOrbit on GitHub" title="OpenOrbit GitHub repository"><SiGithub size={18}/></a></footer></section><ChatAssistant/></main>
}
