import Markdown from 'react-markdown';

/** React escapes text; raw HTML and remote images are never rendered. */
export function WorkspaceMarkdown({content}:{content:string}){
  return <div className="workspace-markdown"><Markdown skipHtml
    disallowedElements={['img','iframe','script','style']}
    urlTransform={url=>/^https?:\/\//i.test(url)?url:''}
    components={{a:({href,children})=>href?<a href={href} target="_blank" rel="noopener noreferrer">{children}</a>:<span>{children}</span>}}>{content}</Markdown></div>;
}
