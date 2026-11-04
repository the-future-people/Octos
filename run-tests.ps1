# The full suite: every test file under apps/, named one by one.
#
# Files, never folders: apps/ has no __init__.py, so a folder or package
# label makes discovery crash ("expected str ... not NoneType").
# Both naming styles: tests*.py (most apps) and test_*.py (inventory's
# tests/ folder, which no full run reached from March to November 2026).
# A tests.py sitting beside a tests/ folder is skipped: Python imports
# the folder, so the file can never run anyway.
#
# Usage:  .\run-tests.ps1            everything
#         .\run-tests.ps1 --keepdb   extra options go straight to Django

$root = (Resolve-Path .).Path
$labels = Get-ChildItem apps -Recurse -File -Include 'tests*.py', 'test_*.py' |
    Where-Object { $_.FullName -notmatch '\\migrations\\' } |
    Where-Object { -not (Test-Path (Join-Path $_.DirectoryName $_.BaseName) -PathType Container) } |
    ForEach-Object { ($_.FullName.Substring($root.Length + 1) -replace '\.py$', '') -replace '\\', '.' }

"$($labels.Count) test modules"
docker-compose --env-file .env.docker exec web python manage.py test @labels @args