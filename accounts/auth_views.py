from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy
from django.shortcuts import redirect, render

from .forms import CustomerPasswordChangeForm, CustomerSignupForm


def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = CustomerSignupForm(request.POST)

        if form.is_valid():
            user = form.save()

            login(request, user)

            messages.success(
                request,
                "Your IDDS account has been created successfully.",
            )

            return redirect("accounts:dashboard")
    else:
        form = CustomerSignupForm()

    return render(
        request,
        "accounts/signup.html",
        {"form": form},
    )


class CustomerPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = CustomerPasswordChangeForm
    success_url = reverse_lazy("accounts:dashboard")

    def form_valid(self, form):
        messages.success(
            self.request,
            "Your password has been changed successfully.",
        )

        return super().form_valid(form)