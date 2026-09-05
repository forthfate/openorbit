import { Settings2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { SectionInfo } from './section-info'

const sectionHints:Record<string,string>={
  'Evaluation build list':'Create and manage evaluation configurations that connect a target, workflow, and evaluation assets.',
  '평가 빌드 목록':'평가 대상, 워크플로, 감독관 자산을 연결한 평가 구성을 관리합니다.',
  '評価ビルド一覧':'評価対象、ワークフロー、評価アセットをつなぐ評価構成を管理します。',
  'Application settings':'Manage console-wide preferences such as language and theme.',
  '애플리케이션 설정':'언어와 테마처럼 이 콘솔 자체에 적용되는 기본 환경을 관리합니다.',
  'アプリケーション設定':'言語やテーマなど、このコンソール自体に適用される基本環境を管理します。',
  'Operational manager prompt':'A console-wide operating prompt, separate from reusable evaluation-build templates.',
  '운영 관리자 프롬프트':'콘솔 전체 운영용 프롬프트이며 평가 빌드 템플릿 자산과는 별개입니다.',
  '運用管理者プロンプト':'コンソール全体の運用プロンプトで、評価ビルド用テンプレートとは別に管理します。',
  'PDCA and AI feedback':'Track improvements proposed by supervisor evaluations and their evidence.',
  'PDCA 및 AI 피드백':'감독관 평가에서 제안된 개선과 근거를 추적합니다.',
  'PDCAとAIフィードバック':'監督AI評価で提案された改善と根拠を追跡します。',
  'Improvement effect':'Compare before-and-after scores and success change.',
  '개선 효과':'개선 전후 점수와 성공 변화율을 비교합니다.',
  '改善効果':'改善前後のスコアと成功差分を比較します。',
  'Runners':'Create reusable runners that execute project-specific automation.',
}
export function PanelHeader({title,action}:{title:ReactNode;action?:ReactNode}){const hint=typeof title==='string'?sectionHints[title]:undefined;return <div className="panel-head"><h2>{hint?<SectionInfo title={title} description={hint}/>:title}</h2>{action??<Settings2 size={18}/>}</div>}
export function MetricCard({label,value}:{label:string;value:string}){const locale=localStorage.getItem('orbit.locale');const caption=locale==='ko'?'실시간 로컬 상태':locale==='ja'?'ライブローカル状態':'live local state';return <article className="metric"><p>{label}</p><strong>{value}</strong><small>{caption}</small></article>}
