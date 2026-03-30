from django.shortcuts import render



def login_view(request):
    return render(request, 'branch_manager/login.html')


def dashboard_view(request):
    return render(request, 'branch_manager/dashboard.html')


def inbox_view(request):
    return render(request, 'branch_manager/inbox.html')


def jobs_view(request):
    return render(request, 'branch_manager/jobs.html')

def cashier_view(request):
    return render(request, 'portals/cashier.html')

def attendant_view(request):
    return render(request, 'portals/attendant.html')

def belt_manager_view(request):
    return render(request, 'portals/belt_manager.html')
