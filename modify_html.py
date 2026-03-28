import os
import re

with open('dashboard_panels.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

block_a = ''.join(lines[20:87])
block_b = ''.join(lines[94:183])
block_c = ''.join(lines[188:423])

with open('templates/index.html', 'r', encoding='utf-8') as f:
    idx_content = f.read()

# Replace old graphs panel (lines 114 to 156 of the current index.html)
# We can find the opening div id="perf-graphs-box" and its end.
new_idx = re.sub(
    r'<!-- Performance Graphs Panel \(hidden until graphs are ready\) -->[\s\S]*?</div>\n\n                    <div style="margin-top:20px;"></div>',
    block_a + '\n                    <div style="margin-top:20px;"></div>',
    idx_content,
    flags=re.DOTALL
)

# Insert the Dashboard tab link if it's missing
if 'data-tab="dashboard"' not in new_idx:
    new_idx = new_idx.replace(
        '<button class="tab-btn" data-tab="performance" id="perf-tab-btn">Performance</button>',
        '<button class="tab-btn" data-tab="performance" id="perf-tab-btn">Performance</button>\n            <button class="tab-btn" data-tab="dashboard">Dashboard</button>'
    )

# Insert Block B (Dashboard tab content)
if 'id="dashboard" class="tab-content' not in new_idx:
    new_idx = new_idx.replace(
        '</section>\n        </main>',
        '</section>\n\n            <!-- Dashboard Panel -->\n' + block_b + '\n        </main>'
    )

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(new_idx)

# Append CSS block C
with open('static/style.css', 'r', encoding='utf-8') as f:
    css_content = f.read()
if '/* ── Perf graphs panel (decrypt tab) ──────────────────────────────────────── */' not in css_content:
    with open('static/style.css', 'a', encoding='utf-8') as f:
        f.write('\n\n/* DASHBOARD PANELS CSS */\n')
        f.write(block_c)

print('Integration complete!')
