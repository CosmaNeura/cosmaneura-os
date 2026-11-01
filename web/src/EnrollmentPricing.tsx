export type SeatSelection = { plan: 'solo' | 'small' | 'negotiated'; humanSeats: number };
export function initialSeatSelection(search: string): SeatSelection {
  const params = new URLSearchParams(search), seats = Number(params.get('seats'));
  if (params.get('plan') === 'small') return {plan:'small',humanSeats:Number.isInteger(seats) && seats >= 2 && seats <= 10 ? seats : 2};
  if (params.get('plan') === 'negotiated') return {plan:'negotiated',humanSeats:Number.isInteger(seats) && seats >= 11 && seats <= 1000 ? seats : 11};
  return {plan:'solo',humanSeats:1};
}
export function selectionForSeats(humanSeats: number): SeatSelection {
  return {plan:humanSeats === 1 ? 'solo' : humanSeats <= 10 ? 'small' : 'negotiated',humanSeats};
}
export const dollars = (cents: number) => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(cents/100);

export function EnrollmentPricing({value,onChange,disabled=false,seatPolicy}:{
  value:SeatSelection;onChange:(next:SeatSelection)=>void;disabled?:boolean;seatPolicy?:string;
}) {
  return <fieldset className="enrollment-pricing" disabled={disabled}>
    <legend>How many people will use CosmaBot?</legend>
    <p id="human-seat-help">Count every human user, including you, providers and office staff. Agents do not count as human seats.</p>
    <div className="enrollment-price-options">
      <label className={value.plan==='solo'?'selected':''}><input type="radio" name="enrollment-plan" checked={value.plan==='solo'} onChange={()=>onChange({plan:'solo',humanSeats:1})}/>
        <span><strong>Solo</strong><b>$300<span>/month</span></b><small>1 human user</small></span></label>
      <label className={value.plan==='small'?'selected':''}><input type="radio" name="enrollment-plan" checked={value.plan==='small'} onChange={()=>onChange({plan:'small',humanSeats:value.humanSeats>=2&&value.humanSeats<=10?value.humanSeats:2})}/>
        <span><strong>Small practice</strong><b>$300 <span>first user</span></b><small>+$100/month for each additional user · 2–10 users</small></span></label>
      <label className={value.plan==='negotiated'?'selected':''}><input type="radio" name="enrollment-plan" checked={value.plan==='negotiated'} onChange={()=>onChange({plan:'negotiated',humanSeats:11})}/>
        <span><strong>11+ users</strong><b>Contact us</b><small>Agree your price before payment</small></span></label>
    </div>
    {value.plan!=='solo'&&<label className="enrollment-seat-count">Human users, including the owner
      {value.plan==='small'?<select id="enrollment-seats" aria-describedby="human-seat-help" value={value.humanSeats} onChange={event=>onChange({...value,humanSeats:Number(event.target.value)})}>
        {Array.from({length:9},(_,i)=>i+2).map(count=><option key={count} value={count}>{count} people</option>)}</select>
        :<input id="enrollment-seats" type="number" min={11} max={1000} step={1} value={value.humanSeats} aria-describedby="human-seat-help" onChange={event=>onChange({...value,humanSeats:Number(event.target.value)})}/>}
    </label>}
    <p className="enrollment-price-total" aria-live="polite">{value.plan==='negotiated'?'A negotiated quote is required.':
      <><strong>{dollars(30000+(value.humanSeats-1)*10000)}/month</strong> for {value.humanSeats} human {value.humanSeats===1?'user':'users'} after your 14-day trial.</>}</p>
    {seatPolicy&&<p className="enrollment-hint">{seatPolicy}</p>}
  </fieldset>;
}
