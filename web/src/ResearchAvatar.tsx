import { useId } from "react";

/** A Dartmouth Green coworker holding public-source research tools. */
export function ResearchAvatar() {
  const body = useId();
  return <svg viewBox="0 0 96 96" width="96" height="96" fill="none">
    <defs><linearGradient id={body} x1="25" y1="20" x2="70" y2="81" gradientUnits="userSpaceOnUse">
      <stop stopColor="#27916A"/><stop offset=".55" stopColor="#00693E"/><stop offset="1" stopColor="#003D25"/>
    </linearGradient></defs>
    <ellipse cx="48" cy="82" rx="30" ry="5" fill="#143C2B" opacity=".13"/>
    <path d="M22 55C22 29 31 16 47 16C64 16 73 30 74 54L77 70C79 80 67 83 49 82C29 84 17 79 19 70Z" fill={`url(#${body})`}/>
    <path d="M28 47C27 30 35 22 43 21" stroke="#65B28B" strokeWidth="5" strokeLinecap="round" opacity=".32"/>
    <ellipse cx="36" cy="39" rx="4" ry="6" fill="#142B22"/>
    <ellipse cx="58" cy="39" rx="4" ry="6" fill="#142B22"/>
    <ellipse cx="35" cy="37" rx="1.2" ry="1.8" fill="#E5F1EB"/>
    <ellipse cx="57" cy="37" rx="1.2" ry="1.8" fill="#E5F1EB"/>
    <path d="M43 48Q47 51 51 48" stroke="#003D25" strokeWidth="2" strokeLinecap="round"/>
    <path d="M27 59L45 55L61 59V77L45 74L27 78Z" fill="#F7F4E8" stroke="#D4DDC8" strokeWidth="1.5"/>
    <path d="M45 56V74M31 63L40 61M31 68L40 66M49 62L56 64" stroke="#A5B99F" strokeWidth="1.5" strokeLinecap="round"/>
    <path d="M25 55C17 55 19 70 28 69" stroke="#23825B" strokeWidth="8" strokeLinecap="round"/>
    <path d="M69 55Q78 60 69 70" stroke="#00613A" strokeWidth="8" strokeLinecap="round"/>
    <circle cx="66" cy="60" r="9" fill="#D5EBDD" fillOpacity=".78" stroke="#E9E7D5" strokeWidth="3"/>
    <path d="M72 67L79 77" stroke="#D5CDAA" strokeWidth="5" strokeLinecap="round"/>
    <path d="M62 57Q63 54 67 54" stroke="#FFFDF4" strokeWidth="2" strokeLinecap="round"/>
  </svg>;
}
