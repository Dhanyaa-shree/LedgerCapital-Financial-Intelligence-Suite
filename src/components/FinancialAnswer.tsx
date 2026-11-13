
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

interface FinancialAnswerProps {
  content: string;
}

function cleanResponse(text: string): string {
  return text
    // Convert bracketed LaTeX expressions to supported math syntax
    .replace(/\\\[/g, '$$$$')
    .replace(/\\\]/g, '$$$$')
    .replace(/\\\(/g, '$')
    .replace(/\\\)/g, '$')

    // Remove separator-only lines
    .replace(/^\s*-{4,}\s*$/gm, '')

    // Remove spaces inside evidence references
    .replace(/\[\s*(K\d+|P\d+)\s*\]/g, '[$1]')

    .trim();
}

export default function FinancialAnswer({
  content,
}: FinancialAnswerProps) {
  return (
    <div className="financial-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1: ({ children }) => (
            <h2 className="text-xl font-semibold mb-3">{children}</h2>
          ),
          h2: ({ children }) => (
            <h3 className="text-lg font-semibold mt-5 mb-2">{children}</h3>
          ),
          h3: ({ children }) => (
            <h4 className="font-semibold mt-4 mb-2">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="mb-3 leading-7">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-6 mb-3 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-6 mb-3 space-y-1">{children}</ol>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-4 rounded-lg border border-slate-700">
              <table className="w-full text-sm border-collapse">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="px-4 py-3 text-left font-semibold bg-slate-800 border-b border-slate-700">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-4 py-3 border-b border-slate-700">
              {children}
            </td>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold">{children}</strong>
          ),
        }}
      >
        {cleanResponse(content)}
      </ReactMarkdown>
    </div>
  );
}
