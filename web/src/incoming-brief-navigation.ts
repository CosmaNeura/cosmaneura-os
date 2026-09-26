import {createContext} from 'react';

/** A navigation hint only. The existing incoming view obtains fresh authority. */
export const IncomingBriefNavigation=createContext<{openTicket:(ticketId:string)=>void;blocked:boolean}|null>(null);
