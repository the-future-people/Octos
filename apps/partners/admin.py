from django.contrib import admin

from apps.partners.models import Partner, PartnerRep


class RepInline(admin.TabularInline):
    model = PartnerRep
    extra = 0
    raw_id_fields = ('lead',)


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'status', 'area', 'primary_phone', 'applied_at')
    list_filter = ('status', 'kind', 'region')
    search_fields = ('name', 'code', 'primary_phone', 'area')
    raw_id_fields = ('customer',)
    filter_horizontal = ('services',)
    inlines = [RepInline]
