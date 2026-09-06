import type { Locale } from '../../locales'

export function PageSizeSelect({locale,value,onChange}:{locale:Locale;value:number;onChange:(value:number)=>void}){
  const label=locale==='ko'?'페이지당 표시':locale==='ja'?'ページごとの表示数':'Items per page'
  const option=(size:number)=>locale==='ko'?`${size}개씩`:locale==='ja'?`${size}件ずつ`:`${size} per page`
  return <label className="page-size-control"><span className="visually-hidden">{label}</span><select value={value} onChange={event=>onChange(Number(event.target.value))}>{[15,30,50,100].map(size=><option key={size} value={size}>{option(size)}</option>)}</select></label>
}
