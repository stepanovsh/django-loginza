# -*- coding: utf-8 -*-
try:
    from django.contrib.auth import get_user_model
except ImportError: # django < 1.5
    from django.contrib.auth.models import User
else:
    User = get_user_model()
from django.db import models
from django.utils import simplejson as json
from django.dispatch import receiver
from django.db.models.signals import post_delete
from django.utils.translation import ugettext_lazy as _

from loginza import signals
from loginza.conf import settings


class IdentityManager(models.Manager):
    def from_loginza_data(self, loginza_data):
        try:
            identity = self.get(identity=loginza_data['identity'])
            # update data as some apps can use it, e.g. avatars
            identity.data = json.dumps(loginza_data)
            identity.save()
        except self.model.DoesNotExist:
            identity = self.create(
                identity=loginza_data['identity'],
                provider=loginza_data['provider'],
                data=json.dumps(loginza_data)
            )
        return identity

    def get_name_and_photo_from_loginza_data(self, identity, user):
        loginza_data = json.loads(identity.data)
        # get all variables
        name = loginza_data.get('name', loginza_data.get('full_name', None))
        nickname = loginza_data.get('nickname', None)
        photo = loginza_data.get('photo', None)

        if name:
            first_name = name.get('first_name', None)
            last_name = name.get('last_name', None)
            full_name = name.get('full_name', None)
        if first_name:
            user.first_name = first_name
        elif full_name:
            user.first_name = full_name
        elif nickname:
            user.first_name = nickname
        else:
            user.first_name = 'noname{}'.format(user.user_map_set.get().id)
        if last_name:
            user.last_name = last_name
        # user._default_manager.filter(id=user.id).update(first_name=user.first_name, last_name=user.last_name)
        if photo:
            user.set_photo_from_url(photo)
        else:
            user.save()
        return ''


class UserMapManager(models.Manager):
    def for_identity(self, identity, request):
        try:
            user_map = self.get(identity=identity)
        except self.model.DoesNotExist:
            # if there is authenticated user - map identity to that user
            # if not - create new user and mapping for him
            # if request.user.is_authenticated():
            #     #user = request.user
            #     pass
            # else:
            loginza_data = json.loads(identity.data)

            loginza_email = loginza_data.get('email', '')
            email = loginza_email if '@' in loginza_email else settings.DEFAULT_EMAIL

            # if nickname is not set - try to get it from email
            # e.g. vgarvardt@gmail.com -> vgarvardt
            loginza_nickname = loginza_data.get('nickname', None)
            if loginza_nickname is None or loginza_nickname == "":
                username = email.split('@')[0]
            else:
                username = loginza_nickname

            # check duplicate user name
            while True:
                try:
                    existing_user = User.objects.get(email=email)
                    username = '%s%d' % (username, existing_user.id)
                    if existing_user.email == settings.DEFAULT_EMAIL:
                            email = '@'.join([username, email.split('@')[-1]])
                except User.DoesNotExist:
                    break

            user = User.objects.create_user(
                email,
                username
            )
            user.save()
            user_map = UserMap.objects.create(identity=identity, user=user)
            signals.created.send(request, user_map=user_map)
        return user_map


class Identity(models.Model):
    identity = models.CharField(_('identity'), max_length=255, unique=True)
    provider = models.CharField(_('provider'), max_length=255)
    data = models.TextField(_('data'))

    objects = IdentityManager()

    def __unicode__(self):
        return self.identity

    class Meta:
        ordering = ['id']
        verbose_name = _('identity')
        verbose_name_plural = _('identities')


class UserMap(models.Model):
    identity = models.OneToOneField(Identity, verbose_name=_('identity'))
    user = models.ForeignKey(User, verbose_name=_('user'))
    verified = models.BooleanField(_('active'), default=False, db_index=True)

    objects = UserMapManager()

    def __unicode__(self):
        return '%s [%s]' % (unicode(self.user), self.identity.provider)

    class Meta:
        ordering = ['user']
        verbose_name = _('user map')
        verbose_name_plural = _('user maps')


@receiver(post_delete, sender=UserMap)
def post_delete_user(sender, instance, *args, **kwargs):
    if instance.identity:
        instance.identity.delete()
