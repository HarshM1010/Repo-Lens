import os
import re
import json
import subprocess
import shutil
import math
from pathlib import Path
import git
import networkx as nx
import requests

# Helper: safe file read
def safe_read_file(path, max_size=1024*1024):
    try:
        if os.path.getsize(path) > max_size:
            return ""
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""

def get_remote_commit_hash(repo_url):
    """
    Get HEAD commit hash of remote repo without cloning.
    """
    try:
        g = git.cmd.Git()
        output = g.ls_remote(repo_url, 'HEAD')
        if output:
            parts = output.split()
            if parts:
                return parts[0]
    except Exception as e:
        print(f"Error fetching remote commit: {e}")
    return None

def clone_repo(repo_url, target_path):
    """
    Clones the repository to target_path.
    """
    if os.path.exists(target_path):
        shutil.rmtree(target_path)
    os.makedirs(target_path, exist_ok=True)
    repo = git.Repo.clone_from(repo_url, target_path, depth=1)
    return repo.head.commit.hexsha

def detect_languages(repo_path):
    """
    Recursively scan files and group by extension/language.
    """
    langs = {}
    total_size = 0
    
    ext_mapping = {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.ts': 'TypeScript',
        '.tsx': 'TypeScript (React)',
        '.jsx': 'JavaScript (React)',
        '.go': 'Go',
        '.rs': 'Rust',
        '.java': 'Java',
        '.cpp': 'C++',
        '.cc': 'C++',
        '.c': 'C',
        '.h': 'C/C++ Header',
        '.cs': 'C#',
        '.rb': 'Ruby',
        '.php': 'PHP',
        '.sh': 'Shell Script',
        '.html': 'HTML',
        '.css': 'CSS',
        '.json': 'JSON',
        '.yml': 'YAML',
        '.yaml': 'YAML',
        '.md': 'Markdown',
    }

    for root, dirs, files in os.walk(repo_path):
        # Skip git folders
        if '.git' in root.split(os.sep):
            continue
        for file in files:
            file_path = os.path.join(root, file)
            try:
                if os.path.islink(file_path):
                    continue
                size = os.path.getsize(file_path)
                ext = os.path.splitext(file)[1].lower()
                lang = ext_mapping.get(ext, 'Other')
                langs[lang] = langs.get(lang, 0) + size
                total_size += size
            except Exception:
                continue

    if not langs:
        return 'Unknown', {}

    # Sort languages by size
    sorted_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)
    primary_lang = sorted_langs[0][0]
    
    # Convert sizes to percentages
    lang_percentages = {}
    for l, size in sorted_langs:
        pct = round((size / total_size) * 100, 2) if total_size > 0 else 0
        if pct > 0.5:  # Only report languages above 0.5%
            lang_percentages[l] = pct

    return primary_lang, lang_percentages

def analyze_structure(repo_path):
    """
    Build a folder hierarchy and compute stats.
    """
    total_files = 0
    total_size = 0
    tree = {}
    
    # We build tree up to depth 3 for visualization
    for root, dirs, files in os.walk(repo_path):
        if '.git' in root.split(os.sep):
            continue
        
        rel_path = os.path.relpath(root, repo_path)
        if rel_path == '.':
            rel_path = ''
            
        parts = rel_path.split(os.sep) if rel_path else []
        
        # Count files
        for file in files:
            fpath = os.path.join(root, file)
            try:
                total_files += 1
                total_size += os.path.getsize(fpath)
            except Exception:
                continue
                
        # Build structure tree up to depth 3
        if len(parts) <= 3:
            curr = tree
            for part in parts:
                if part not in curr:
                    curr[part] = {}
                curr = curr[part]
            
            # Add files inside current directory
            for file in files:
                curr[file] = "file"

    # Human readable size
    size_str = "0 B"
    if total_size > 0:
        size_name = ("B", "KB", "MB", "GB")
        i = int(math.floor(math.log(total_size, 1024)))
        p = math.pow(1024, i)
        s = round(total_size / p, 2)
        size_str = f"{s} {size_name[i]}"

    return {
        'total_files': total_files,
        'total_size_bytes': total_size,
        'total_size_human': size_str,
        'structure': tree
    }

def analyze_dependencies(repo_path):
    """
    Scan manifest files to extract dependency details.
    """
    deps = []
    
    for root, dirs, files in os.walk(repo_path):
        if '.git' in root.split(os.sep):
            continue
            
        for file in files:
            fpath = os.path.join(root, file)
            # Python requirements
            if file == 'requirements.txt':
                content = safe_read_file(fpath)
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Parse package name (e.g., django==5.0 or django>=5.0)
                        match = re.match(r'^([a-zA-Z0-9_\-\[\]]+)', line)
                        if match:
                            pkg = match.group(1)
                            version = line[len(pkg):].strip(' =<>~') or 'latest'
                            deps.append({'name': pkg, 'version': version, 'manager': 'pip', 'file': 'requirements.txt'})
            
            # Node package.json
            elif file == 'package.json':
                content = safe_read_file(fpath)
                try:
                    data = json.loads(content)
                    for dep_type in ['dependencies', 'devDependencies']:
                        if dep_type in data:
                            for name, ver in data[dep_type].items():
                                deps.append({'name': name, 'version': ver, 'manager': 'npm/yarn', 'file': 'package.json'})
                except Exception:
                    pass
            
            # Go mod
            elif file == 'go.mod':
                content = safe_read_file(fpath)
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith('require '):
                        parts = line.split()
                        if len(parts) >= 3:
                            deps.append({'name': parts[1], 'version': parts[2], 'manager': 'go mod', 'file': 'go.mod'})
            
            # Rust Cargo.toml
            elif file == 'Cargo.toml':
                content = safe_read_file(fpath)
                in_dependencies = False
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith('[dependencies]'):
                        in_dependencies = True
                    elif line.startswith('[') and line.endswith(']'):
                        in_dependencies = False
                    elif in_dependencies and '=' in line:
                        parts = line.split('=')
                        pkg = parts[0].strip()
                        version = parts[1].strip().strip('"\'')
                        deps.append({'name': pkg, 'version': version, 'manager': 'cargo', 'file': 'Cargo.toml'})

    return deps

def calculate_metrics(repo_path):
    """
    Run radon complexity/maintainability checks on python.
    Also count functions/classes.
    """
    total_loc = 0
    total_comments = 0
    total_blank = 0
    python_files = 0
    
    maintainability_scores = []
    complexity_scores = []
    
    classes_count = 0
    functions_count = 0
    largest_file_name = "N/A"
    largest_file_size = 0
    largest_file_loc = 0
    
    for root, dirs, files in os.walk(repo_path):
        if '.git' in root.split(os.sep):
            continue
        for file in files:
            fpath = os.path.join(root, file)
            try:
                sz = os.path.getsize(fpath)
                if sz > largest_file_size:
                    largest_file_size = sz
                    largest_file_name = os.path.relpath(fpath, repo_path)
            except Exception:
                continue

            ext = os.path.splitext(file)[1].lower()
            
            # Basic Line Counter
            if ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.cpp', '.c', '.cs', '.php', '.rb']:
                content = safe_read_file(fpath)
                lines = content.splitlines()
                loc = len(lines)
                total_loc += loc
                
                if fpath == os.path.join(repo_path, largest_file_name):
                    largest_file_loc = loc

                # Simple regex count for functions and classes
                if ext == '.py':
                    python_files += 1
                    classes_count += len(re.findall(r'^\s*class\s+\w+', content, re.MULTILINE))
                    functions_count += len(re.findall(r'^\s*def\s+\w+', content, re.MULTILINE))
                    
                    # Run radon if available
                    try:
                        from radon.complexity import cc_visit
                        from radon.metrics import mi_visit
                        
                        cc_res = cc_visit(content)
                        if cc_res:
                            for item in cc_res:
                                complexity_scores.append(item.complexity)
                                
                        mi_val = mi_visit(content, multi=True)
                        if mi_val is not None:
                            maintainability_scores.append(mi_val)
                    except Exception:
                        pass
                else:
                    # Generic code counters for JS/Go/Rust
                    classes_count += len(re.findall(r'\bclass\s+\w+', content))
                    functions_count += len(re.findall(r'\bfunction\s+\w+|\bdef\s+\w+|\bfn\s+\w+|func\s+\w+', content))

    # Calculate averages
    avg_complexity = round(sum(complexity_scores) / len(complexity_scores), 2) if complexity_scores else 6.0
    avg_maintainability = round(sum(maintainability_scores) / len(maintainability_scores), 2) if maintainability_scores else 80.0
    
    # Map index to grade
    if avg_maintainability >= 80:
        mi_grade = 'A'
    elif avg_maintainability >= 60:
        mi_grade = 'B'
    elif avg_maintainability >= 40:
        mi_grade = 'C'
    else:
        mi_grade = 'D'

    return {
        'loc': total_loc,
        'functions': functions_count,
        'classes': classes_count,
        'largest_file': f"{largest_file_name} ({largest_file_loc} lines / {round(largest_file_size/1024, 2)} KB)",
        'cyclomatic_complexity': avg_complexity,
        'maintainability_index': avg_maintainability,
        'maintainability_grade': mi_grade,
    }

def run_security_scan(repo_path):
    """
    Search for hardcoded secrets, eval calls, and run Bandit.
    """
    vulnerabilities = []
    secrets_count = 0
    dangerous_func_count = 0
    
    # Secret scanning regexes
    secret_rules = {
        'Slack Webhook': r'https://hooks\.slack\.com/services/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+',
        'Generic API Key': r'(?i)(api_key|apikey|secret_key|secretkey|access_token|private_key|auth_token)\s*[:=]\s*["\']([a-zA-Z0-9_\-\.\~]{16,})["\']',
        'AWS Secret Key': r'(?i)aws_secret_access_key\s*[:=]\s*["\']([a-zA-Z0-9+/]{40})["\']',
        'JWT Token': r'eyJhbGciOi[a-zA-Z0-9-_]+\.[a-zA-Z0-9-_]+\.[a-zA-Z0-9-_]+',
        'Database Password': r'(?i)(postgresql|mysql|mongodb)://[a-zA-Z0-9_]+:[a-zA-Z0-9_]+@',
    }
    
    dangerous_funcs = {
        '.py': [
            (r'\beval\s*\(', 'High', 'Use of eval() function is highly discouraged as it runs arbitrary code.'),
            (r'\bexec\s*\(', 'High', 'Use of exec() runs arbitrary code dynamically.'),
            (r'\bos\.system\s*\(', 'Medium', 'os.system() bypasses process boundaries. Use subprocess instead.'),
            (r'shell\s*=\s*True', 'Medium', 'subprocess with shell=True is vulnerable to shell injection.'),
        ],
        '.js': [
            (r'\beval\s*\(', 'High', 'Use of eval() is dangerous and leads to remote code execution.'),
            (r'\bchild_process\.exec\s*\(', 'Medium', 'Verify arguments to child_process.exec to prevent shell injections.'),
        ],
        '.ts': [
            (r'\beval\s*\(', 'High', 'Use of eval() is dangerous and leads to remote code execution.'),
        ]
    }

    for root, dirs, files in os.walk(repo_path):
        if '.git' in root.split(os.sep):
            continue
        for file in files:
            fpath = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()
            
            if ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', '.yml', '.env', '.json']:
                content = safe_read_file(fpath)
                rel_fpath = os.path.relpath(fpath, repo_path)
                
                # Check Secrets
                for rule_name, rule_regex in secret_rules.items():
                    matches = re.finditer(rule_regex, content)
                    for m in matches:
                        secrets_count += 1
                        line_no = content.count('\n', 0, m.start()) + 1
                        vulnerabilities.append({
                            'file': rel_fpath,
                            'line': line_no,
                            'type': 'Hardcoded Secret',
                            'severity': 'Critical',
                            'description': f'Hardcoded {rule_name} was discovered.'
                        })
                
                # Check Dangerous Functions
                rules = dangerous_funcs.get(ext, [])
                for rule_regex, severity, desc in rules:
                    matches = re.finditer(rule_regex, content)
                    for m in matches:
                        dangerous_func_count += 1
                        line_no = content.count('\n', 0, m.start()) + 1
                        vulnerabilities.append({
                            'file': rel_fpath,
                            'line': line_no,
                            'type': 'Dangerous Function',
                            'severity': severity,
                            'description': desc
                        })

    # Run bandit on python if available
    try:
        has_python = any(f.endswith('.py') for root, d, files in os.walk(repo_path) for f in files)
        if has_python:
            # We run bandit programmatically or via subprocess.
            # Programmatic execution:
            cmd = ['bandit', '-r', repo_path, '-f', 'json']
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.stdout:
                data = json.loads(res.stdout)
                for issue in data.get('results', []):
                    rel_fpath = os.path.relpath(issue['filename'], repo_path)
                    vulnerabilities.append({
                        'file': rel_fpath,
                        'line': issue['line_number'],
                        'type': f"Bandit: {issue['test_id']}",
                        'severity': issue['issue_severity'].title(),
                        'description': issue['issue_text']
                    })
    except Exception as e:
        print(f"Bandit run bypassed: {e}")

    # Deduct points for vulnerabilities
    security_score = 100
    for v in vulnerabilities:
        sev = v['severity'].lower()
        if sev == 'critical':
            security_score -= 15
        elif sev == 'high':
            security_score -= 10
        elif sev == 'medium':
            security_score -= 5
        else:
            security_score -= 2
            
    security_score = max(0, security_score)

    return {
        'vulnerabilities': vulnerabilities,
        'secrets_count': secrets_count,
        'dangerous_func_count': dangerous_func_count,
        'security_score': security_score,
    }

def generate_dependency_graph(repo_path):
    """
    Build a NetworkX import graph and export nodes and edges.
    """
    G = nx.DiGraph()
    
    # Scan python, JS/TS import patterns
    py_import_pattern = re.compile(r'^\s*(?:import\s+([a-zA-Z0-9_\.,\s]+)|from\s+([a-zA-Z0-9_\.]+)\s+import\s+([a-zA-Z0-9_\.,\s\*]+))')
    js_import_pattern = re.compile(r'(?:import\s+.*\s+from\s+["\'](.*)["\']|require\s*\(\s*["\'](.*)["\']\s*\))')
    
    for root, dirs, files in os.walk(repo_path):
        if '.git' in root.split(os.sep):
            continue
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in ['.py', '.js', '.ts', '.tsx', '.jsx']:
                fpath = os.path.join(root, file)
                rel_fpath = os.path.relpath(fpath, repo_path)
                
                # Add node
                G.add_node(rel_fpath, type='file', size=os.path.getsize(fpath))
                
                content = safe_read_file(fpath)
                lines = content.splitlines()
                
                for line in lines:
                    if ext == '.py':
                        match = py_import_pattern.match(line)
                        if match:
                            imp, frm, _ = match.groups()
                            target_pkg = frm or imp
                            if target_pkg:
                                # Clean up names (e.g. from utils.helpers import x -> utils)
                                target_clean = target_pkg.split('.')[0].strip()
                                # Link file to package/module
                                if not G.has_node(target_clean):
                                    G.add_node(target_clean, type='module')
                                G.add_edge(rel_fpath, target_clean)
                    elif ext in ['.js', '.ts', '.tsx', '.jsx']:
                        match = js_import_pattern.search(line)
                        if match:
                            imp1, imp2 = match.groups()
                            target = imp1 or imp2
                            if target:
                                # e.g. ./utils or react
                                if target.startswith('.'):
                                    # Try to map to relative file path
                                    try:
                                        target_path = os.path.normpath(os.path.join(os.path.dirname(rel_fpath), target))
                                        # Add suffix checks
                                        found = False
                                        for suffix in ['', '.js', '.ts', '.jsx', '.tsx']:
                                            candidate = target_path + suffix
                                            if os.path.exists(os.path.join(repo_path, candidate)) and not os.path.isdir(os.path.join(repo_path, candidate)):
                                                if not G.has_node(candidate):
                                                    G.add_node(candidate, type='file')
                                                G.add_edge(rel_fpath, candidate)
                                                found = True
                                                break
                                        if not found:
                                            # Treat as module node
                                            if not G.has_node(target_path):
                                                G.add_node(target_path, type='module')
                                            G.add_edge(rel_fpath, target_path)
                                    except Exception:
                                        pass
                                else:
                                    if not G.has_node(target):
                                        G.add_node(target, type='module')
                                    G.add_edge(rel_fpath, target)

    # Prune graph for frontend presentation if too large (cap at 60 nodes)
    if G.number_of_nodes() > 60:
        # Keep nodes with highest degree
        degrees = dict(G.degree())
        sorted_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:60]
        nodes_to_keep = [n[0] for n in sorted_nodes]
        G = G.subgraph(nodes_to_keep).copy()

    # Format nodes & edges for Vis.js
    nodes = []
    for node, data in G.nodes(data=True):
        ntype = data.get('type', 'module')
        label = os.path.basename(node) if ntype == 'file' else node
        # color configuration
        color = '#6366f1' if ntype == 'file' else '#06b6d4'
        nodes.append({
            'id': node,
            'label': label,
            'title': f"Type: {ntype}<br>Path: {node}",
            'color': color,
            'shape': 'dot' if ntype == 'file' else 'triangle',
            'size': 15 if ntype == 'file' else 10
        })
        
    edges = []
    for u, v in G.edges():
        edges.append({
            'from': u,
            'to': v,
            'arrows': 'to'
        })
        
    return {
        'nodes': nodes,
        'edges': edges
    }

def generate_ai_documentation(repo_name, language, summary, metrics, security, gemini_api_key):
    """
    Produce structured Markdown. If Gemini key is set, call Gemini API.
    Otherwise, generate high-quality fallback heuristics.
    """
    if gemini_api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={gemini_api_key}"
            prompt = f"""
You are an expert system architect analyzing the repository '{repo_name}'.
Language: {language}
Metrics: {json.dumps(metrics)}
Vulnerabilities Score: {security.get('security_score', 100)}

Please generate a professional production-grade repository architecture and documentation guide.
Format as Markdown with the following headings:
# Project Overview
Provide a summary of what the project is, its primary stack, and its purpose.

# Architecture & Design
Explain how the code is structured.

# Component Explanations
Highlight major directories, modules, and entrypoints.

# Recommendations & Improvements
Suggest architectural, security, and complexity improvements.
"""
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            res = requests.post(url, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                md_text = data['candidates'][0]['content']['parts'][0]['text']
                return md_text
        except Exception as e:
            print(f"Gemini API request failed: {e}. Falling back to default generator.")

    # High quality local fallback generator
    mi_grade = metrics.get('maintainability_grade', 'A')
    loc = metrics.get('loc', 0)
    sec_score = security.get('security_score', 100)
    vuln_count = len(security.get('vulnerabilities', []))
    
    md = f"""# RepoLens Heuristic Documentation - {repo_name}

Welcome to the automated documentation report generated by **RepoLens** static analysis core engines.

---

## 🚀 Project Overview

The repository **{repo_name}** is built primarily in **{language}**. Based on codebase patterns, it is structured as a modular codebase implementing standard practices. 

- **Primary Stack**: {language}
- **Lines of Code (LOC)**: {loc}
- **Detected Classes**: {metrics.get('classes', 0)}
- **Detected Functions**: {metrics.get('functions', 0)}
- **Largest Code Asset**: `{metrics.get('largest_file', 'N/A')}`

---

## 🏛️ Architecture & Design

The repository's layout follows a standard design pattern:
1. **Core Domain**: Operations are grouped by features or modules.
2. **Configuration layer**: System environment settings are configured in setup files and package dependencies.
3. **Execution context**: Entrypoints are defined in parent modules.

The codebase maintainability is graded **{mi_grade}** with an average cyclomatic complexity of **{metrics.get('cyclomatic_complexity', 0)}**.

---

## 🔍 Major Components & Directories

Based on our directory structure analysis:
- **Dependency Manifests**: Extracted packages reflect deployment setups.
- **Entrypoints**: The root files coordinate package behaviors.
- **Metric Highlights**:
  - Code Maintainability Index: **{metrics.get('maintainability_index', 0)}**
  - High complexity files: Identified assets with larger lines of code.

---

## 🛡️ Security Assessment & Vulnerability Analysis

The project scored **{sec_score}/100** on our security scale.
- We discovered **{security.get('secrets_count', 0)}** hardcoded secrets.
- We detected **{security.get('dangerous_func_count', 0)}** dangerous script function calls (such as `eval`, `exec`, or unsafe process executions).
- Total vulnerability items logged: **{vuln_count}**.

### Recommended Security Fixes
1. **Environment Variables**: Inject credentials/secrets via OS variables rather than committing them in plain text.
2. **Safe Parsing**: Replace dangerous executions with standard serializers or standard processes (e.g. avoiding shell evaluation).

---

## 📈 Suggested Improvements

1. **Reduce File Coupling**: Refactor complex modules (such as `{metrics.get('largest_file', 'N/A')}`) into separate services.
2. **Increase Unit Coverage**: Implement automated unit tests to verify entrypoint modules.
3. **Continuous Integration**: Add automated linting checks (e.g., Radon, Bandit) to prevent code quality regression.
"""
    return md
