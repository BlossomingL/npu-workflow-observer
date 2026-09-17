import * as vscode from 'vscode';
import * as net from 'net';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { randomUUID } from 'crypto';

const execFileAsync = promisify(execFile);

function cfg() {
  const c = vscode.workspace.getConfiguration('npuObserver');
  return {host: c.get<string>('host', '127.0.0.1'), port: c.get<number>('port', 43189)};
}

function send(event: any) {
  const {host, port} = cfg();
  const socket = net.createConnection({host, port}, () => {
    socket.write(JSON.stringify(event) + '\n');
    socket.end();
  });
  socket.on('error', () => {});
}

async function gitDiff(cwd: string, file: string): Promise<string> {
  try {
    const {stdout} = await execFileAsync('git', ['diff', '--no-ext-diff', '--unified=3', '--', file], {cwd, maxBuffer: 2_000_000});
    return stdout.slice(0, 200_000);
  } catch { return ''; }
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument(async (doc) => {
    if (doc.uri.scheme !== 'file') return;
    const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
    const cwd = folder?.uri.fsPath ?? process.cwd();
    const diff = await gitDiff(cwd, doc.uri.fsPath);
    send({
      event_id: randomUUID(), timestamp: new Date().toISOString(), name: 'source.file.saved', kind: 'event',
      source: 'vscode', cwd, attributes: {file: doc.uri.fsPath, language: doc.languageId, diff}
    });
  }));

  context.subscriptions.push(vscode.commands.registerCommand('npuObserver.recordDecision', async () => {
    const decision = await vscode.window.showInputBox({prompt: 'What decision did you make?'});
    if (!decision) return;
    const reason = await vscode.window.showInputBox({prompt: 'Why? Evidence / hypothesis (optional)'});
    send({
      event_id: randomUUID(), timestamp: new Date().toISOString(), name: 'decision.created', kind: 'event',
      source: 'vscode', cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
      attributes: {decision, reason: reason ? [reason] : []}
    });
    vscode.window.showInformationMessage('NPU Observer: decision recorded');
  }));
}

export function deactivate() {}
