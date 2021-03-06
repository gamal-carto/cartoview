from urlparse import urljoin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max, Min, F
from django.forms.util import ErrorList
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.shortcuts import render, render_to_response
from PIL import Image, ImageOps
# Create your views here.
from guardian.shortcuts import get_perms
from cartoview.app_manager.forms import AppInstanceEditForm
from geonode.base.forms import CategoryForm
from geonode.base.models import TopicCategory
from geonode.people.forms import ProfileForm
from geonode.security.views import _perms_info_json
from models import *
from apps_helper import *
from django.conf import settings as django_settings
from django.core import management
from threading import Timer
import json
from geonode.utils import resolve_object, build_social_links
from django.utils.translation import ugettext as _
from django.template import RequestContext, loader
from django.core.files import File

_PERMISSION_MSG_DELETE = _("You are not permitted to delete this document")
_PERMISSION_MSG_GENERIC = _("You do not have permissions for this document.")
_PERMISSION_MSG_MODIFY = _("You are not permitted to modify this document")
_PERMISSION_MSG_METADATA = _(
    "You are not permitted to modify this document's metadata")
_PERMISSION_MSG_VIEW = _("You are not permitted to view this document")

current_folder, filename = os.path.split(os.path.abspath(__file__))
temp_dir = os.path.join(current_folder, 'temp')

def save_thumbnail(filename, image):
    thumb_folder = 'thumbs'
    upload_path = os.path.join(django_settings.MEDIA_ROOT, thumb_folder)
    if not os.path.exists(upload_path):
        os.makedirs(upload_path)

    with open(os.path.join(upload_path, filename), 'wb') as f:
        thumbnail = File(f)
        thumbnail.write(image)

    url_path = os.path.join(django_settings.MEDIA_URL, thumb_folder, filename).replace('\\', '/')
    url = urljoin(django_settings.SITEURL, url_path)

    return url

def save_uploaded_file(f, path):
    destination = open(path, 'wb+')
    for chunk in f.chunks():
        destination.write(chunk)
    destination.close()


def get_attr(obj, key, default):
    try:
        return obj[key]
    except:
        return default


def add_app(app_name, info):
    app = App()
    app.name = app_name
    app.title = get_attr(info, 'title', app_name)
    app.description = get_attr(info, 'description', None)
    app.short_description = get_attr(info, 'short_description', None)
    app.owner_url = get_attr(info, 'owner_url', None)
    app.help_url = get_attr(info, 'help_url', None)

    #     data = r.read()
    #
    #     img_temp = NamedTemporaryFile()
    #     img_temp.write(data)
    #     img_temp.flush()
    #     app.app_img.save(app_name+'.png', File(img_temp))
    # app_logo_path = os.path.abspath(os.path.join(BASE_DIR,'apps',app_name,'logo.png'))
    # if os.path.isfile(app_logo_path):
    #     r_logo = open(app_logo_path,'rb')
    #     data_logo = r_logo.read()
    #
    #     img_temp_logo = NamedTemporaryFile()
    #     img_temp_logo.write(data_logo)
    #     img_temp_logo.flush()
    #     app.app_logo.save(app_name+'_logo.png', File(img_temp_logo))
    app.author = get_attr(info, 'author', None)
    app.author_website = get_attr(info, 'author_website', None)
    app.home_page = get_attr(info, 'home_page', None)
    app.license = get_attr(info, 'licence', None)
    app.single_instance = get_attr(info, 'single_instance', False)
    app.in_menu = get_attr(info, 'in_menu', True)
    app.admin_only = get_attr(info, 'admin_only', False)
    apps = App.objects.all()
    if apps:
        app.order = apps.aggregate(Max('order'))['order__max'] + 1
    else:
        app.order = 1
    app.save()
    CARTOVIEW_ROOT = getattr(django_settings, 'CARTOVIEW_ROOT', None)
    app_img_path = os.path.abspath(os.path.join(CARTOVIEW_ROOT,'apps',app_name,'app_img.png'))
    if os.path.isfile(app_img_path):
        from cStringIO import StringIO
        size = 200, 150
        img = Image.open(app_img_path)
        img = ImageOps.fit(img, size, Image.ANTIALIAS)
        imgfile = StringIO()
        img.save(imgfile, format='PNG')
        imgvalue =  imgfile.getvalue()
        filename = 'app-%s-thumb.png' % app.pk
        app_img_url = save_thumbnail(filename, imgvalue)
        app.app_img_url=app_img_url
        app.save()
    tags = get_attr(info, 'tags', [])
    for tag_name in tags:
        try:
            tag = AppTag(name=tag_name)
            tag.save()
            app.tags.add(tag)
        except:
            pass
    # from django.db.models import loading
    # django_settings.INSTALLED_APPS+=('cartoview.apps.'+app_name,)
    # loading.cache.loaded = False
    management.call_command('syncdb', interactive=False)


def finalize_setup(app_name, user):
    def install():
        try:
            installer = importlib.import_module('cartoview.apps.%s.installer' % app_name)
            add_app(app_name, installer.info)
            installer.install()
        except:
            pass

    restart_server_batch = getattr(django_settings, 'RESTART_SERVER_BAT', None)
    if restart_server_batch:
        def restart():
            install_app(app_name)
            install()
            run_batch_file(restart_server_batch, None, APPS_DIR)

        timer = Timer(0.1, restart)
        timer.start()
    else:
        try:
            install_app(app_name)
        except:
            pass
        install()


@login_required
def install_app_view(request):
    Apps = installed_apps()
    menu_apps = App.objects.filter(is_suspended=False).filter(in_menu=True).order_by('order')
    non_menu_apps = App.objects.filter(is_suspended=False).filter(in_menu=False).order_by('order')
    context = {'Apps': Apps}
    context['menu_apps'] = menu_apps
    context['non_menu_apps'] = non_menu_apps
    return render(request, 'app_manager/app_install.html', context)


def index(request):
    Apps = installed_apps()
    for app in Apps:
        module = importlib.import_module('cartoview.apps.' + app.name)
        if hasattr(module, 'urls_dict'):
            urls_dict = getattr(module, 'urls_dict')
            if 'admin' in urls_dict.keys():
                app.admin_urls = urls_dict['admin']
            else:
                app.admin_urls = None
            if 'logged_in' in urls_dict.keys():
                app.logged_in_urls = urls_dict['logged_in']
            else:
                app.logged_in_urls = None
            if 'anonymous' in urls_dict.keys():
                app.anonymous_urls = urls_dict['anonymous']
            else:
                app.anonymous_urls = None
        else:
            app.admin_urls = app.logged_in_urls = app.anonymous_urls = None

    context = {'Apps': Apps}
    return render(request, 'app_manager/apps.html', context)


@login_required
def ajax_install_app(request):
    import tempfile
    import zipfile
    response_data = {
        'success': False,
        'log': [],
        'errors': [],
        'warnings': [],
    }

    package_file = request.FILES.get('package_file', None)
    if package_file is None:
        response_data["errors"].append("No package file uploaded")
    else:
        response_data["log"].append("Package file uploaded")
        extract_to = tempfile.mkdtemp(dir=temp_dir)
        x, uploaded_file_path = tempfile.mkstemp(dir=temp_dir)
        save_uploaded_file(package_file, uploaded_file_path)
        # Get a real Python file handle on the uploaded file
        file_handle = open(uploaded_file_path, 'rb')
        # Unzip the file, creating subdirectories as needed
        zfobj = zipfile.ZipFile(file_handle)
        for name in zfobj.namelist():
            if name.startswith('__MACOSX/'):
                continue
            if name.endswith('/'):
                try:  # Don't try to create a directory if exists
                    os.mkdir(os.path.join(extract_to, name))
                except:
                    pass
            else:
                outfile = open(os.path.join(extract_to, name), 'wb')
                outfile.write(zfobj.read(name))
                outfile.close()
        response_data["log"].append("Package file extracted")
        app_name = os.listdir(extract_to)[0]
        no_installer = True
        response_data["app_name"] = app_name
        app_dir = os.path.join(extract_to, app_name)
        installed_app_dir = os.path.join(APPS_DIR, app_name)
        if os.path.isdir(installed_app_dir):
            response_data['warnings'].append('application %s is already exists' % app_name)
        else:
            shutil.move(app_dir, APPS_DIR)
            try:
                installer = importlib.import_module('cartoview.apps.%s.installer' % app_name)
                no_installer = False
            except:
                pass
        response_data["success"] = True
        if no_installer:
            response_data['warnings'].append('no application installer found')

        os.close(x)
        zfobj.close()
        file_handle.close()
        os.remove(uploaded_file_path)

        shutil.rmtree(extract_to)
        finalize_setup(app_name, request.user)
        response_data["log"].append("Running installation scripts...")
    return HttpResponse(json.dumps(response_data), content_type="application/json")


@login_required
def uninstall_app(request, app_name):
    try:
        installer = importlib.import_module('cartoview.apps.%s.installer' % app_name)
        installer.uninstall()
        app = App.objects.get(name=app_name)
        app.delete()
        response_data = {"success": True}
    except Exception as ex:
        response_data = {"success": False, "errors": [ex.message]}

    return HttpResponse(json.dumps(response_data), content_type="application/json")


@login_required
def move_up(request, app_id):
    app = App.objects.get(id=app_id)
    prev_app = App.objects.get(order=App.objects.filter(order__lt=app.order).aggregate(Max('order'))['order__max'])
    order = app.order
    app.order = prev_app.order
    prev_app.order = order
    app.save()
    prev_app.save()
    return HttpResponse(json.dumps({"success": True}), content_type="application/json")


@login_required
def move_down(request, app_id):
    app = App.objects.get(id=app_id)
    next_app = App.objects.get(order=App.objects.filter(order__gt=app.order).aggregate(Min('order'))['order__min'])
    order = app.order
    app.order = next_app.order
    next_app.order = order
    app.save()
    next_app.save()
    return HttpResponse(json.dumps({"success": True}), content_type="application/json")


def suspend_app(request, app_id):
    app = App.objects.get(id=app_id)
    app.is_suspended = True
    app.save()
    return HttpResponse(json.dumps({"success": True}), content_type="application/json")


def resume_app(request, app_id):
    app = App.objects.get(id=app_id)
    app.is_suspended = False
    app.save()
    return HttpResponse(json.dumps({"success": True}), content_type="application/json")


def save_app_orders(request):
    if request.method == 'POST':
        apps_list = request.POST.get('apps', None)

        if apps_list:
            try:
                apps = json.loads(apps_list)
                menu_apps = apps['menu_apps']
                non_menu_apps = apps['non_menu_apps']
                for idx, val in enumerate(menu_apps):
                    app = App.objects.get(id=int(val['id']))
                    app.order = idx
                    app.in_menu = True
                    app.save()

                for idx, val in enumerate(non_menu_apps):
                    app = App.objects.get(id=int(val['id']))
                    app.order = idx + len(menu_apps)
                    app.in_menu = False
                    app.save()
                ajax_vars = {'success': True}
            except:
                ajax_vars = {'success': False}
                return HttpResponse(json.dumps(ajax_vars), content_type="application/json")

    return HttpResponse(json.dumps(ajax_vars), content_type="application/json")


def _resolve_appinstance(request, appinstanceid, permission='base.change_resourcebase',
                         msg=_PERMISSION_MSG_GENERIC, **kwargs):
    """
    Resolve the document by the provided primary key and check the optional permission.
    """
    return resolve_object(request, AppInstance, {'pk': appinstanceid},
                          permission=permission, permission_msg=msg, **kwargs)


def appinstance_detail(request, appinstanceid):
    """
    The view that show details of each document
    """
    appinstance = None
    try:
        appinstance = _resolve_appinstance(
            request,
            appinstanceid,
            'base.view_resourcebase',
            _PERMISSION_MSG_VIEW)

    except Http404:
        return HttpResponse(
            loader.render_to_string(
                '404.html', RequestContext(
                    request, {
                    })), status=404)

    except PermissionDenied:
        return HttpResponse(
            loader.render_to_string(
                '401.html', RequestContext(
                    request, {
                        'error_message': _("You are not allowed to view this document.")})), status=403)

    if appinstance is None:
        return HttpResponse(
            'An unknown error has occured.',
            mimetype="text/plain",
            status=401
        )

    else:
        if request.user != appinstance.owner and not request.user.is_superuser:
            AppInstance.objects.filter(id=appinstance.id).update(popular_count=F('popular_count') + 1)
        #appinstance_links = appinstance.link_set.filter(link_type__in=['appinstance_view', 'appinstance_edit'])
        set_thumbnail_link = appinstance.link_set.filter(link_type='appinstance_thumbnail')
        context_dict = {
            'perms_list': get_perms(request.user, appinstance.get_self_resource()),
            'permissions_json': _perms_info_json(appinstance),
            'resource': appinstance,
            #'appinstance_links': appinstance_links,
            'set_thumbnail_link': set_thumbnail_link
            # 'imgtypes': IMGTYPES,
            # 'related': related
        }

        if geonode_settings.SOCIAL_ORIGINS:
            context_dict["social_links"] = build_social_links(request, appinstance)

        if getattr(geonode_settings, 'EXIF_ENABLED', False):
            try:
                from geonode.contrib.exif.utils import exif_extract_dict
                exif = exif_extract_dict(appinstance)
                if exif:
                    context_dict['exif_data'] = exif
            except:
                print "Exif extraction failed."

        return render_to_response(
            "app_manager/appinstance_detail.html",
            RequestContext(request, context_dict))


@login_required
def appinstance_metadata(
        request,
        appinstanceid,
        template='app_manager/appinstance_metadata.html'):
    appinstance = None
    try:
        appinstance = _resolve_appinstance(
            request,
            appinstanceid,
            'base.change_resourcebase_metadata',
            _PERMISSION_MSG_METADATA)

    except Http404:
        return HttpResponse(
            loader.render_to_string(
                '404.html', RequestContext(
                    request, {
                    })), status=404)

    except PermissionDenied:
        return HttpResponse(
            loader.render_to_string(
                '401.html', RequestContext(
                    request, {
                        'error_message': _("You are not allowed to edit this instance.")})), status=403)

    if appinstance is None:
        return HttpResponse(
            'An unknown error has occured.',
            mimetype="text/plain",
            status=401
        )

    else:
        poc = appinstance.poc
        metadata_author = appinstance.metadata_author
        topic_category = appinstance.category

        if request.method == "POST":
            appinstance_form = AppInstanceEditForm(
                request.POST,
                instance=appinstance,
                prefix="resource")
            category_form = CategoryForm(
                request.POST,
                prefix="category_choice_field",
                initial=int(
                    request.POST["category_choice_field"]) if "category_choice_field" in request.POST else None)
        else:
            appinstance_form = AppInstanceEditForm(instance=appinstance, prefix="resource")
            category_form = CategoryForm(
                prefix="category_choice_field",
                initial=topic_category.id if topic_category else None)

        if request.method == "POST" and appinstance_form.is_valid(
        ) and category_form.is_valid():
            new_poc = appinstance_form.cleaned_data['poc']
            new_author = appinstance_form.cleaned_data['metadata_author']
            new_keywords = appinstance_form.cleaned_data['keywords']
            new_category = TopicCategory.objects.get(
                id=category_form.cleaned_data['category_choice_field'])

            if new_poc is None:
                if poc is None:
                    poc_form = ProfileForm(
                        request.POST,
                        prefix="poc",
                        instance=poc)
                else:
                    poc_form = ProfileForm(request.POST, prefix="poc")
                if poc_form.is_valid():
                    if len(poc_form.cleaned_data['profile']) == 0:
                        # FIXME use form.add_error in django > 1.7
                        errors = poc_form._errors.setdefault('profile', ErrorList())
                        errors.append(_('You must set a point of contact for this resource'))
                        poc = None
                if poc_form.has_changed and poc_form.is_valid():
                    new_poc = poc_form.save()

            if new_author is None:
                if metadata_author is None:
                    author_form = ProfileForm(request.POST, prefix="author",
                                              instance=metadata_author)
                else:
                    author_form = ProfileForm(request.POST, prefix="author")
                if author_form.is_valid():
                    if len(author_form.cleaned_data['profile']) == 0:
                        # FIXME use form.add_error in django > 1.7
                        errors = author_form._errors.setdefault('profile', ErrorList())
                        errors.append(_('You must set an author for this resource'))
                        metadata_author = None
                if author_form.has_changed and author_form.is_valid():
                    new_author = author_form.save()

            if new_poc is not None and new_author is not None:
                the_appinstance = appinstance_form.save()
                the_appinstance.poc = new_poc
                the_appinstance.metadata_author = new_author
                the_appinstance.keywords.add(*new_keywords)
                AppInstance.objects.filter(id=the_appinstance.id).update(category=new_category)

                return HttpResponseRedirect(
                    reverse(
                        'appinstance_detail',
                        args=(
                            appinstance.id,
                        )))
            else:
                the_appinstance = appinstance_form.save()
                if new_poc is None:
                    the_appinstance.poc = appinstance.owner
                if new_author is None:
                    the_appinstance.metadata_author = appinstance.owner
                the_appinstance.keywords.add(*new_keywords)
                AppInstance.objects.filter(id=the_appinstance.id).update(category=new_category)

                return HttpResponseRedirect(
                    reverse(
                        'appinstance_detail',
                        args=(
                            appinstance.id,
                        )))

        if poc is not None:
            appinstance_form.fields['poc'].initial = poc.id
            poc_form = ProfileForm(prefix="poc")
            poc_form.hidden = True
        else:
            poc_form = ProfileForm(prefix="poc")
            poc_form.hidden = True
        if metadata_author is not None:
            appinstance_form.fields['metadata_author'].initial = metadata_author.id
            author_form = ProfileForm(prefix="author")
            author_form.hidden = True
        else:
            author_form = ProfileForm(prefix="author")
            author_form.hidden = True

        return render_to_response(template, RequestContext(request, {
            "appinstance": appinstance,
            "appinstance_form": appinstance_form,
            "poc_form": poc_form,
            "author_form": author_form,
            "category_form": category_form,
        }))


def appinstance_remove(request, appinstanceid):
    try:
        appinstance = _resolve_appinstance(
            request,
            appinstanceid,
            'base.delete_resourcebase',
            _PERMISSION_MSG_DELETE)
        appinstance.delete()
        return HttpResponseRedirect(reverse('appinstance_browse'))
    except PermissionDenied:
        return HttpResponse(
            'You are not allowed to delete this Instance',
            mimetype="text/plain",
            status=401
        )
